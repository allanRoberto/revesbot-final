"""
Processor de Monitoramento de Sinais - SIMPLIFICADO

Processa todos os sinais de forma unificada.
Suporta o fluxo PAI/FILHO do pattern NUMEROS_PUXANDO.
"""

import json, os
import logging
import time
import asyncio
from datetime import datetime
import aiohttp
from datetime import datetime
from typing import Optional

import redis.asyncio as aioredis
from redis.exceptions import ResponseError
from src.config import settings
from src.models import Signal
from core.redis import save_signal

def get_figure(number):
    figure_mapping = {
        0 : [10, 20, 30],
        1 : [1, 10, 19, 28],
        2 : [2, 11, 20, 29],
        3 : [3, 12, 21, 30],
        4 : [4, 13, 22, 31],
        5 : [5, 14, 23, 32],
        6 : [6, 15, 24, 33],
        7 : [7, 16, 25, 34],
        8 : [8, 17, 26, 35],
        9 : [9, 18, 27, 36],
        10 :[1, 10, 19, 28]
    }

    return figure_mapping.get(number, [])

def get_color(cls, num: int) -> str:
        """Retorna a cor"""
        if num == 0:
            return 'green'
        return 'red' if num in cls.RED_NUMBERS else 'black'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SignalProcessor:
    """Processador de sinais."""
    PRE_WINDOW_SIZE = 4
    def __init__(self):
        self.redis_client = None
        self.results_redis_client = None
        self.result_channel = settings.result_channel
        self.bet_api_url = os.getenv("BET_API_URL", "http://localhost:3000/api/bet")
        self.monitoring_window = int(os.getenv("MONITORING_ASSERTIVITY_WINDOW", "20"))
        self.monitoring_min_assertivity = float(os.getenv("MONITORING_ASSERTIVITY_MIN", "20"))
        self.monitoring_min_samples = int(os.getenv("MONITORING_ASSERTIVITY_MIN_SAMPLES", "8"))
        # Valor padrão da ficha (pode ser configurado via env ou signal)
        self.default_bet_value = float(os.getenv("DEFAULT_BET_VALUE", "0.50"))

    async def _get_redis(self):
        if self.redis_client is None:
            self.redis_client = aioredis.from_url(settings.signals_redis_url, decode_responses=True)
        return self.redis_client

    async def _get_results_redis(self):
        if self.results_redis_client is None:
            self.results_redis_client = aioredis.from_url(settings.results_redis_url, decode_responses=True)
        return self.results_redis_client

    @staticmethod
    def _can_fallback_lset_error(exc: Exception) -> bool:
        """Permite fallback somente para ausência da lista ou índice inválido."""
        if not isinstance(exc, ResponseError):
            return False
        reason = str(exc).lower()
        return "no such key" in reason or "index out of range" in reason

    async def _update_signal_snapshot_head(self, redis_client, key: str, payload: str, signal_id: str) -> None:
        """
        Atualiza o snapshot no índice 0 com fallback conservador:
        - tenta LSET (comportamento atual)
        - se key ausente/índice inválido, faz LPUSH+LTRIM
        - para outros erros, propaga sem mascarar
        """
        try:
            await redis_client.lset(key, 0, payload)
            return
        except Exception as exc:
            if not self._can_fallback_lset_error(exc):
                raise
            logger.warning(
                "[PERSIST] fallback aplicado signal_id=%s key=%s op=LSET motivo=%s",
                signal_id,
                key,
                str(exc),
            )
            await redis_client.lpush(key, payload)
            await redis_client.ltrim(key, 0, 0)

    # ══════════════════════════════════════════════════════════════════════════
    # MONITOR PRINCIPAL
    # ══════════════════════════════════════════════════════════════════════════
    async def monitor_single_signal(self, signal_data: dict):
        """Monitora um sinal escutando o canal de resultados."""
        redis = await self._get_results_redis()


         # Detecta modo
        self.is_simulation = os.getenv("SIMULATION_MODE", "false").lower() == "true"
        self.training_mode = os.getenv("TRAINING_MODE", "false").lower() == "true"


        pubsub = redis.pubsub()
        await pubsub.subscribe(self.result_channel)
        
        signal = Signal.model_validate(signal_data)
        
        
        try:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=5)
                
                if message is None:
                    await asyncio.sleep(0.05)
                    continue
                
                data = json.loads(message["data"])
                slug = data.get("slug")
                number = data.get("result")
                
                if slug != signal.roulette_id:
                    continue
                
                if number is None:
                    continue

                signal.history.insert(0, number)
                signal.passed_spins += 1 
                await self._persist_and_publish(signal)

                # Processar o spin
                should_stop = await self._process_spin(signal, number)
                
                if should_stop:
                    break
                    
        except Exception as e:
            logger.error(f"[MONITOR] Erro: {e}", exc_info=True)
        finally:
            await pubsub.unsubscribe(self.result_channel)

    async def monitor_single_signal_queue(
        self,
        signal_data: dict,
        queue: asyncio.Queue,
        startup_future: Optional[asyncio.Future] = None,
    ):
        """Monitora um sinal recebendo resultados via fila."""
        try:
            signal = Signal.model_validate(signal_data)
        except Exception as exc:
            if startup_future is not None and not startup_future.done():
                startup_future.set_exception(exc)
            raise

        try:
            # Marca startup somente após validação essencial e entrada no fluxo de monitoramento.
            if startup_future is not None and not startup_future.done():
                startup_future.set_result(str(signal.id))

            while True:
                number = await queue.get()

                signal.history.insert(0, number)
                signal.passed_spins += 1
                await self._persist_and_publish(signal)

                should_stop = await self._process_spin(signal, number)
                if should_stop:
                    break
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"[MONITOR QUEUE] Erro: {e}", exc_info=True)
    
    # ══════════════════════════════════════════════════════════════════════════
    # PROCESSAMENTO DO SPIN
    # ══════════════════════════════════════════════════════════════════════════
    
    async def _process_spin(self, signal: Signal, number: int) -> bool:
        """
        Processa um spin para o sinal.
        
        Returns:
            True se o sinal deve parar de ser monitorado
        """
    
        status = signal.status

        await self._persist_and_publish(signal)
        # ══════════════════════════════════════════════════════════════════
        # STATUS: WAITING (PAI esperando gatilho)
        # ══════════════════════════════════════════════════════════════════
        if status == "waiting":
            return await self._process_waiting(signal, number)
        
        # ══════════════════════════════════════════════════════════════════
        # STATUS: PROCESSING (FILHO apostando)
        # ══════════════════════════════════════════════════════════════════
        elif status == "processing":
            return await self._process_processing(signal, number)
        
        # ══════════════════════════════════════════════════════════════════
        # STATUS: MONITORING (FILHO apostando)
        # ══════════════════════════════════════════════════════════════════
        elif status == "monitoring":
            return await self._process_monitoring(signal, number)
        

        # ══════════════════════════════════════════════════════════════════
        # STATUS: COMPLETED / WIN / LOST / MONITORING (finalizado)
        # ══════════════════════════════════════════════════════════════════
       # Sinais finalizados - continua monitorando para coletar dados
        if signal.status in ("win", "lost", "cancelled", "monitoring_win", "monitoring_lost"):
            
            # Se ACABOU de mudar neste spin, pula
            if status not in ("win", "lost", "cancelled", "monitoring_win", "monitoring_lost"):
                return False
            
            # Tratamento para monitoring_win e monitoring_lost
            if signal.status in ("monitoring_win", "monitoring_lost"):
                # Finaliza imediatamente - não precisa monitorar após
                return True

            if signal.status == "lost":

                signal.spins_after_lost += 1
                signal.passed_spins -= 1

                #if activation_num <= 1 :
                   # if signal.attempts >= 6 : 
                        #await self._create_child(signal, number, temp_state, "RECICLAGEM", "processing")
                        

                if signal.greens_after_lost == 0 :
                    signal.attempts += 1

                if number in (signal.bets or []):
                    signal.greens_after_lost += 1
                    signal.greens_after_lost_at.append(signal.spins_after_lost)  # NOVO
                    signal.log.append(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ BATEU APÓS LOSS! Número: {number} (spin #{signal.spins_after_lost})")
                    signal.message = f"⚠️ Bateu {signal.greens_after_lost}x após LOSS nos spins {signal.greens_after_lost_at} - {signal.message} \n\n\n"
                    await self._persist_and_publish(signal)
                    return False
                
                if signal.spins_after_lost >= 15:
                    return True

            elif signal.status == "win":
                signal.spins_after_win += 1
                signal.passed_spins -= 1
                
                if number in (signal.bets or []):
                    signal.greens_after_win += 1
                    signal.greens_after_win_at.append(signal.spins_after_win)  # NOVO
                    signal.log.append(f"[{datetime.now().strftime('%H:%M:%S')}] 🔥 BATEU APÓS WIN! Número: {number} (spin #{signal.spins_after_win})")
                    signal.message = f"🔥 Bateu {signal.greens_after_win}x após WIN nos spins {signal.greens_after_win_at} - {signal.message} \n\n\n"
                    await self._persist_and_publish(signal)
                    return False
                
                if signal.spins_after_win >= 15:
                    return True

            elif signal.status == "cancelled":
                signal.spins_after_cancelled += 1
                signal.passed_spins -= 1

                
                if number in (signal.bets or []):
                    signal.greens_after_cancelled += 1
                    signal.greens_after_cancelled_at.append(signal.spins_after_cancelled)  # NOVO
                    signal.log.append(f"[{datetime.now().strftime('%H:%M:%S')}] ❄️ BATEU APÓS CANCEL! Número: {number} (spin #{signal.spins_after_cancelled})")
                    signal.message = f"❄️ Bateu {signal.greens_after_cancelled}x após CANCEL nos spins {signal.greens_after_cancelled_at} - {signal.message} \n\n\n"
                    await self._persist_and_publish(signal)
                    return False
                
                if signal.spins_after_cancelled >= 15:
                    return True
            
            return False

        else:
            return True
            
    
    # ══════════════════════════════════════════════════════════════════════════
    # WAITING - PAI ESPERANDO GATILHO
    # ══════════════════════════════════════════════════════════════════════════
    
    async def _process_waiting(self, signal: Signal, number: int) -> bool:
        
        # ══════════════════════════════════════════════════════════════════
        # Verificar se é gatilho
        # ══════════════════════════════════════════════════════════════════
        triggers = signal.triggers or []
        
        if number in triggers:
            signal.status = "processing"
            await self._persist_and_publish(signal)
            return False
     # ══════════════════════════════════════════════════════════════════
     # ══════════════════════════════════════════════════════════════════════════
    
    # ══════════════════════════════════════════════════════════════════════════
    # PROCESSING - FILHO APOSTANDO
    # ══════════════════════════════════════════════════════════════════════════
    async def _process_processing(self, signal: Signal, number: int) -> bool:
        """
        Processa FILHO no status PROCESSING.

        - Incrementa attempts
        - Se número em bets → WIN
        - Se attempts >= gales → LOST
        - Envia aposta INDIVIDUALMENTE a cada tentativa (não todos os gales de uma vez)
        - NÃO envia aposta durante espera (spins_required)
        """

        bets = signal.bets or []
        temp_state = signal.temp_state or {}

        # Inicializa temp_state se necessário
        if signal.temp_state is None:
            signal.temp_state = {}
            temp_state = signal.temp_state

        # Obtém o valor da ficha (pode vir do signal.temp_state ou usar o padrão)
        bet_value = float(temp_state.get("bet_value", self.default_bet_value))

        # ══════════════════════════════════════════════════════════════════
        # ESPERA POR SPINS REQUIRED - NÃO aposta durante espera
        # ══════════════════════════════════════════════════════════════════
        if signal.spins_required >= 1:
            # Se pagaria durante a espera, cancela o sinal para evitar entrada encavalada.
            if number in bets:
                signal.status = "cancelled"
                signal.paid_waiting = True
                signal.spins_required = max(0, signal.spins_required - 1)
                self._log(signal, f"❄️ CANCELADO NA ESPERA - Número {number} pagaria durante spin de espera")
                signal.message = (
                    f"❄️ CANCELADO NA ESPERA - Número {number} já pagaria durante aguardando entrada - "
                    f"{signal.message} \n\n\n"
                )
                await self._persist_and_publish(signal)
                return False

            signal.spins_required -= 1
            self._log(signal, f"⏳ [ESPERA] Aguardando... Restam {signal.spins_required} spins - Número: {number}")
            signal.message = f"⏳ AGUARDANDO - Restam {signal.spins_required} spins para apostar - {signal.message}"
            await self._persist_and_publish(signal)
            return False

        # ══════════════════════════════════════════════════════════════════
        # FLUXO NORMAL - Pronto para apostar!
        # ══════════════════════════════════════════════════════════════════

        signal.attempts += 1
        gales = signal.gales or 3
        current_gale = signal.attempts

        self._log(signal, f"🎲 Gale {current_gale}/{gales} - Número: {number}")

        # ══════════════════════════════════════════════════════════════════
        # ENVIO DA APOSTA PARA O BOT AUTOMÁTICO (a cada tentativa individual)
        # ══════════════════════════════════════════════════════════════════
        self._log(signal, f"🤖 Enviando aposta para bot automático - Gale {current_gale}/{gales} - Valor: R${bet_value:.2f}")

        # Envia a aposta individual em background (fire and forget - não bloqueia)
        self._send_single_bet_fire_and_forget(signal, current_gale, bet_value)

        signal.message = f"🎰 Aposta enviada (Gale {current_gale}/{gales}, R${bet_value:.2f}) - {signal.message}"
        await self._persist_and_publish(signal)

        if number in bets:
            # ✅ WIN!
            signal.status = "win"
            signal.message = f"✅ WIN! Número {number} (Gale {current_gale}) - {signal.message} \n\n\n"
            self._log(signal, f"✅ WIN! Número {number}")

            await self._persist_and_publish(signal)
            return False

        else:
            if signal.attempts >= gales:
                # LOST - Acabaram os gales
                signal.status = "lost"
                signal.broadcasted = True
                signal.message = f"❌ LOST! Não bateu em {gales} gales - {signal.message} \n\n\n"
                self._log(signal, f"❌ LOST!")

                await self._persist_and_publish(signal)
                return False

            else:
                # Ainda tem gales restantes
                next_gale = signal.attempts + 1
                self._log(signal, f"🔄 Próximo: Gale {next_gale}/{gales}")

                # Continua tentando
                signal.message = f"🔄 Gale {current_gale}/{gales} - RED - Número {number} - {signal.message} \n\n\n"
                await self._persist_and_publish(signal)
                return False
    

     # ══════════════════════════════════════════════════════════════════════════
    # PROCESSING - MONITOR
    # ══════════════════════════════════════════════════════════════════════════
    
    async def _process_monitoring(self, signal: Signal, number: int) -> bool:
        """
        Processa sinal no status MONITORING.
        
        Não aposta de verdade, apenas observa para coletar dados da tendência.
        
        - Incrementa attempts
        - Se número em bets → monitoring_win
        - Se attempts >= gales → monitoring_lost
        """
        
       
        bets = signal.bets or []


        signal.attempts += 1
        gales = signal.gales or 3
        
        
        self._log(signal, f"👁️ [MONITORING] Gale {signal.attempts}/{gales} - Número: {number}")
        
        if number in bets:
            # ✅ WIN (monitorado, não apostou)
            signal.status = "monitoring_win"
            signal.message = f"👁️ MONITORING WIN! Número {number} (Gale {signal.attempts}) - Teria ganho! - {signal.message}"
            self._log(signal, f"👁️ MONITORING WIN! Número {number}")
            
            await self._persist_and_publish(signal)

            return False
            
        
        else:
            if signal.attempts >= gales:
                # ❌ LOST (monitorado, não apostou)
                signal.status = "monitoring_lost"
                signal.message = f"👁️ MONITORING LOST! Não bateu em {gales} gales - {signal.message}"
                self._log(signal, f"👁️ MONITORING LOST!")
                
                await self._persist_and_publish(signal)
               
                return False
            
            else:
                # Continua monitorando
                signal.message = f"👁️ [MONITORING] Gale {signal.attempts}/{gales} - Número {number} - {signal.message}"
                await self._persist_and_publish(signal)
                return False
    
    
    def _send_single_bet_fire_and_forget(self, signal: Signal, gale_number: int, bet_value: float):
        """
        Envia UMA aposta individual para o bot automático de forma não-bloqueante.

        NOVO SISTEMA: Envia aposta a cada tentativa (gale) individualmente,
        não todos os gales de uma vez. Isso permite controlar quando apostar
        (não aposta durante espera).

        Args:
            signal: Objeto Signal com os dados da aposta
            gale_number: Número do gale atual (1, 2, 3...)
            bet_value: Valor da ficha a ser apostada
        """
        # Cria task em background para não bloquear
        asyncio.create_task(self._do_send_single_bet(signal, gale_number, bet_value))

    async def _do_send_single_bet(self, signal: Signal, gale_number: int, bet_value: float):
        """Executa o envio da aposta individual em background."""

        payload = {
            "bets": signal.bets or [],
            "roulette_url": signal.roulette_url,
            "gale": gale_number,  # Gale atual (não o total)
            "gales": 1,  # Sempre 1 - uma tentativa por vez
            "valor": bet_value,
            "signal_id": str(signal.id),
        }

        agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"[{agora}] [AUTO BOT] 🤖 Enviando aposta INDIVIDUAL: {len(signal.bets or [])} números | Gale {gale_number} | Valor R${bet_value:.2f}")
        logger.info(f"[{agora}] [AUTO BOT] 📦 Payload: {payload}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.bet_api_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    result = await response.json()
                    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    if response.status == 200 and result.get("success"):
                        logger.info(f"[{agora}] [AUTO BOT] ✅ Aposta Gale {gale_number} enviada com sucesso!")
                    elif response.status == 503:
                        # Mesa offline ou reconectando
                        status = result.get("status", "unknown")
                        if status == "table_offline":
                            logger.warning(f"[{agora}] [AUTO BOT] ⚠️ Mesa offline - aposta ignorada (Gale {gale_number})")
                        elif status == "table_reconnecting":
                            logger.warning(f"[{agora}] [AUTO BOT] ⚠️ Mesa reconectando - aposta ignorada (Gale {gale_number})")
                        else:
                            logger.warning(f"[{agora}] [AUTO BOT] ⚠️ Serviço indisponível (Gale {gale_number}): {result}")
                    else:
                        logger.warning(f"[{agora}] [AUTO BOT] ⚠️ Resposta do bot Gale {gale_number}: {result}")

        except aiohttp.ClientConnectorError:
            agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logger.error(f"[{agora}] [AUTO BOT] ❌ Bot offline - não foi possível conectar")
        except asyncio.TimeoutError:
            agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logger.error(f"[{agora}] [AUTO BOT] ❌ Timeout ao conectar com o bot")
        except Exception as e:
            agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logger.error(f"[{agora}] [AUTO BOT] ❌ Erro Gale {gale_number}: {e}")

    def _send_bet_to_auto_bot_fire_and_forget(self, signal: Signal, gales: int):
        """
        [DEPRECATED] Envia aposta para o bot automático com todos os gales de uma vez.
        Mantido para compatibilidade. Use _send_single_bet_fire_and_forget para o novo sistema.
        """
        # Cria task em background para não bloquear
        asyncio.create_task(self._do_send_bet_to_auto_bot(signal, gales))

    async def _do_send_bet_to_auto_bot(self, signal: Signal, gales: int):
        """[DEPRECATED] Executa o envio da aposta em background (todos os gales)."""

        payload = {
            "bets": signal.bets or [],
            "roulette_url": signal.roulette_url,
            "gales": gales,
        }

        agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"[{agora}] [AUTO BOT] 🤖 Enviando aposta: {len(signal.bets or [])} números | {gales} gales ")
        logger.info(f"[{agora}] [AUTO BOT] 📦 Payload: {payload}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.bet_api_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    result = await response.json()
                    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    if response.status == 200 and result.get("success"):
                        logger.info(f"[{agora}] [AUTO BOT] ✅ Aposta enviada com sucesso!")
                    else:
                        logger.warning(f"[{agora}] [AUTO BOT] ⚠️ Resposta do bot: {result}")

        except aiohttp.ClientConnectorError:
            agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logger.error(f"[{agora}] [AUTO BOT] ❌ Bot offline - não foi possível conectar")
        except asyncio.TimeoutError:
            agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logger.error(f"[{agora}] [AUTO BOT] ❌ Timeout ao conectar com o bot")
        except Exception as e:
            agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logger.error(f"[{agora}] [AUTO BOT] ❌ Erro: {e}")

    async def _place_bet_via_api(self, signal: Signal, gale_number: int = 1, valor : float = 0.50) -> dict:
        """
        Envia aposta para a API externa via POST.
        
        Args:
            signal: Objeto Signal com os dados da aposta
            gale_number: Número do gale (1, 2, 3...)
        """
        # Aguarda 2 segundos antes de enviar a aposta
        agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        logger.info(f"[{agora}] - [BET API] ⏳ Aguardando 2 segundos antes de enviar GALE {gale_number}...")

        time.sleep(2)

        payload = {
            "bets": signal.bets,
            #"bets": [0],
            "valor": valor,
            "attempts": 1,
            "gales": 1,
            "roulette_url": signal.roulette_url,
            "signal_id": str(signal.id),
        }
        agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"[{agora}] - [BET API] 🎰 Enviando GALE {gale_number}: {signal.roulette_name} - {len(signal.bets or [])} números")
        

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.bet_api_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=300)
                ) as response:
                    result = await response.json()
                    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    logger.info(f"[{agora}] - [BET API] ✅ Resposta GALE {gale_number}: {result}")
                    return result
        except Exception as e:
            agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logger.error(f"[{agora}] - [BET API] ❌ Erro ao chamar API de apostas (GALE {gale_number}): {e}")
            return {"success": False, "error": str(e)}
        
    async def _create_child(self, parent: Signal, trigger_number: int, pattern_name, status):
        """Cria sinal FILHO quando gatilho é ativado."""
        
        save_signal(
            roulette_id=parent.roulette_id,
            roulette_name=parent.roulette_name,
            roulette_url=parent.roulette_url,
            triggers=parent.triggers,
            targets=parent.targets or [],
            bets=parent.bets or [],
            snapshot=[],
            status=status, 
            pattern=pattern_name,
            broadcasted=True,
            passed_spins=0,
            spins_required=0,
            gales= 4,
            score=0,
            message=f"Apostando após derrota {trigger_number}",
            temp_state={
                "is_child": True,
                "parent_id": str(parent.id),
                "trigger_number": trigger_number,
                "activation_number": 0,
            },
            tags=["numeros_puxando", "child", f"parent"],
        )
        
        parent.message = f"RECICLAGEM criada - \n\n\n {parent.message}"
        await self._persist_and_publish(parent)
    
   
   
    # ══════════════════════════════════════════════════════════════════════════
    # HELPERS
    # ══════════════════════════════════════════════════════════════════════════    
    def _log(self, signal: Signal, message: str):
        """Adiciona log ao sinal."""
        timestamp = datetime.now().strftime('%H:%M:%S')
        entry = f"[{timestamp}] {message}"
        if signal.log is None:
            signal.log = []
        signal.log.append(entry)
        logger.info(f"[{signal.id}] {message}")

    
    async def _persist_and_publish(self, signal: Signal):
        """Persiste e publica atualização do sinal."""
        
        redis = await self._get_redis()
        key = f"signal:{signal.id}"

        
        
        try:
            payload_dict = {
                "id": str(signal.id),
                "roulette_id": signal.roulette_id,
                "roulette_name": signal.roulette_name,
                "roulette_url": signal.roulette_url,
                "pattern": signal.pattern,
                "triggers": signal.triggers,
                "targets": signal.targets,
                "bets": signal.bets,
                "status": signal.status,
                "history": signal.history,
                "snapshot": signal.snapshot,
                "passed_spins": signal.passed_spins,
                "gales": signal.gales,
                "score": signal.score,
                "attempts": signal.attempts,
                "message": signal.message,
                "tags": signal.tags,
                "temp_state": signal.temp_state,
                "log": signal.log,
                "created_at": signal.created_at,
                "timestamp": signal.created_at,
                "broadcasted": signal.broadcasted,
                "spins_after_win": signal.spins_after_win,
                "greens_after_win": signal.greens_after_win,
                "greens_after_win_at": signal.greens_after_win_at,
                "spins_after_lost": signal.spins_after_lost,
                "greens_after_lost": signal.greens_after_lost,
                "greens_after_lost_at": signal.greens_after_lost_at,
                "spins_after_cancelled": signal.spins_after_cancelled,
                "greens_after_cancelled": signal.greens_after_cancelled,
                "greens_after_cancelled_at": signal.greens_after_cancelled_at,
            }
            
            payload = json.dumps(payload_dict, default=str, ensure_ascii=False)
            
            # Atualizar no Redis com fallback estrito apenas para key ausente/índice inválido.
            await self._update_signal_snapshot_head(redis, key, payload, str(signal.id))
            
            # Stream de updates
            await redis.xadd(
                "streams:signals:updates",
                {
                    "signal_id": str(signal.id),
                    "status": signal.status,
                    "data": payload
                },
                maxlen=50000
            )
            
            # Gerenciar índice de ativos
            if signal.status in ("win", "lost", "cancelled", "completed", "monitoring_win", "monitoring_lost"):
                await redis.hdel("signals:active", str(signal.id))
            else:
                await redis.hset("signals:active", str(signal.id), payload)
                
        except Exception as e:
            logger.error(f"[PERSIST] Erro: {e}", exc_info=True)
            raise

    def _check_inversion(self, signal: Signal) -> Optional[int]:
        """
        Verifica se algum número da aposta ocorreu na janela de inversão
        imediatamente antes do gatilho (últimos PRE_WINDOW_SIZE spins),
        usando signal.snapshot.
        Retorna o número da aposta paga ou None.
        """
        # history[0] é o spin mais recente (o gatilho em _process_spin),
        # então pegamos os PRE_WINDOW_SIZE spins seguintes: índices 1..PRE_WINDOW_SIZE
        nums = signal.history

        # precisa ter ao menos PRE_WINDOW_SIZE+1 elementos (gatilho + janela)
        if len(nums) < self.PRE_WINDOW_SIZE + 1:
            return None

        # elementos imediatamente antes do gatilho
        window = nums[1 : self.PRE_WINDOW_SIZE + 1]

        bets_set = set(signal.bets or [])

        # verifica interseção de sets para eficiência
        #bets_set = set(signal.bets or [])
        common = bets_set.intersection(window)

        return next(iter(common)) if common else None

        
    



        

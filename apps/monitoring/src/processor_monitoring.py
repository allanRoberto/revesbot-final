"""
Processor de Monitoramento de Sinais.

Nesta etapa o monitoring processa exclusivamente o pattern de subtracao,
replicando a ordem operacional do script legado:
- forma o sinal no gatilho
- arma a entrada antes do proximo giro
- usa o giro seguinte para resolver a entrada armada
- aplica pausa por turbulencia quando necessario
"""

import json, os
import logging
import time
import asyncio
from datetime import datetime
import aiohttp
from typing import Optional

import redis.asyncio as aioredis
from redis.exceptions import ResponseError

from .config import settings
from .models import Signal

try:
    from apps.monitoring.core.redis import save_signal
except ImportError:
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
    FINAL_STATUSES = {"win", "lost", "cancelled", "completed", "monitoring_win", "monitoring_lost"}

    def __init__(self):
        self.redis_client = None
        self.results_redis_client = None
        self.result_channel = settings.result_channel
        self.bet_api_url = os.getenv("BET_API_URL", "http://localhost:3000/api/bet")
        self.auto_bet_enabled = os.getenv("MONITORING_AUTO_BET_ENABLED", "false").lower() == "true"
        self.monitoring_window = int(os.getenv("MONITORING_ASSERTIVITY_WINDOW", "20"))
        self.monitoring_min_assertivity = float(os.getenv("MONITORING_ASSERTIVITY_MIN", "20"))
        self.monitoring_min_samples = int(os.getenv("MONITORING_ASSERTIVITY_MIN_SAMPLES", "8"))
        # Valor padrão da ficha (pode ser configurado via env ou signal)
        self.default_bet_value = float(os.getenv("DEFAULT_BET_VALUE", "0.50"))
        self.subtracao_pause_spins = int(os.getenv("SUBTRACAO_PAUSE_SPINS", "2"))
        self.subtracao_entry_values = [
            float(os.getenv("SUBTRACAO_FICHA_E1", "1.0")),
            float(os.getenv("SUBTRACAO_FICHA_E2", "1.0")),
            float(os.getenv("SUBTRACAO_FICHA_E3", "1.5")),
            float(os.getenv("SUBTRACAO_FICHA_E4", "2.5")),
        ]

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

        try:
            signal = Signal.model_validate(signal_data)
            await self._initialize_signal(signal)

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
            await self._initialize_signal(signal)
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

        if signal.status in self.FINAL_STATUSES:
            return True

        if signal.status != "processing":
            signal.status = "processing"

        return await self._process_processing(signal, number)

    async def _initialize_signal(self, signal: Signal) -> None:
        """Prepara o sinal para o fluxo da subtracao antes do primeiro spin."""
        state = self._ensure_subtracao_state(signal)

        if signal.status in self.FINAL_STATUSES:
            await self._persist_and_publish(signal)
            return

        signal.status = "processing"

        if state["pausa_restante"] > 0:
            signal.message = self._build_pause_message(state)
            await self._persist_and_publish(signal)
            return

        if state["entry_armed"]:
            await self._persist_and_publish(signal)
            return

        await self._arm_current_entry(signal, "Sinal iniciado")

    async def _process_processing(self, signal: Signal, number: int) -> bool:
        """
        Processa o ciclo operacional da subtracao.

        O giro atual sempre resolve uma entrada previamente armada.
        Quando necessario, o processor abre pausa por turbulencia antes de
        armar a proxima entrada.
        """
        state = self._ensure_subtracao_state(signal)
        results_history = state["resultados_girados"]
        results_history.append(number)

        if state["pausa_restante"] > 0 and not state["entry_armed"]:
            return await self._process_pause_spin(signal, number, state)

        if not state["entry_armed"]:
            await self._arm_current_entry(signal, f"Retomada sem entrada armada (numero {number})")
            return False

        max_entries = signal.gales or len(state["entry_bet_values"])
        current_entry = int(state.get("current_entry") or (state["entradas_feitas"] + 1))

        state["entry_armed"] = False
        state["entradas_feitas"] = current_entry
        signal.attempts = current_entry

        self._log(signal, f"🎲 Resultado da E{current_entry}/{max_entries}: {number}")

        if number in (signal.bets or []):
            signal.status = "win"
            signal.broadcasted = True
            signal.message = self._build_final_message(
                state=state,
                result="WIN",
                hit_number=number,
                current_entry=current_entry,
            )
            self._log(signal, f"✅ WIN | numero {number} | entrada E{current_entry}")
            await self._persist_and_publish(signal)
            return True

        if current_entry >= max_entries:
            signal.status = "lost"
            signal.broadcasted = True
            signal.message = self._build_final_message(
                state=state,
                result="LOST",
                hit_number=None,
                current_entry=current_entry,
            )
            self._log(signal, f"❌ LOST | esgotou E{current_entry}/{max_entries}")
            await self._persist_and_publish(signal)
            return True

        if self._verificar_turbulencia(number, state["ref_escada"]):
            state["pausa_restante"] = self.subtracao_pause_spins
            pause_message = f"Iniciou pausa no {number} (Entrada {current_entry})"
            state["historico_pausas"].append(pause_message)
            state["ref_escada"] = number
            self._log(signal, f"⏸ {pause_message}")
            signal.message = self._build_pause_message(state)
            await self._persist_and_publish(signal)
            return False

        state["ref_escada"] = number
        await self._arm_current_entry(signal, f"Após RED no numero {number}")
        return False

    async def _process_pause_spin(self, signal: Signal, number: int, state: dict) -> bool:
        if self._verificar_turbulencia(number, state["ref_escada"]):
            state["pausa_restante"] = self.subtracao_pause_spins
            renewal_message = f"Renovou pausa no {number} (Turbulencia continua)"
            state["historico_pausas"].append(renewal_message)
            self._log(signal, f"⏸ {renewal_message}")
        else:
            state["pausa_restante"] = max(0, int(state["pausa_restante"]) - 1)

        state["ref_escada"] = number

        if state["pausa_restante"] == 0:
            resume_message = f"Pausa acabou no {number}. Voltando a apostar."
            state["historico_pausas"].append(resume_message)
            self._log(signal, f"▶ {resume_message}")
            await self._arm_current_entry(signal, f"Pausa encerrada no numero {number}")
            return False

        signal.message = self._build_pause_message(state)
        await self._persist_and_publish(signal)
        return False

    async def _arm_current_entry(self, signal: Signal, reason: str) -> None:
        state = self._ensure_subtracao_state(signal)
        max_entries = signal.gales or len(state["entry_bet_values"])
        next_entry = int(state["entradas_feitas"]) + 1

        if next_entry > max_entries:
            return

        bet_value = self._get_entry_bet_value(state, next_entry)
        state["entry_armed"] = True
        state["current_entry"] = next_entry
        state["current_bet_value"] = bet_value
        signal.message = (
            f"🎰 Aposta armada E{next_entry}/{max_entries} | "
            f"valor R$ {bet_value:.2f} | aguardando proximo giro"
        )
        self._log(signal, f"🎰 E{next_entry}/{max_entries} armada | valor R$ {bet_value:.2f} | {reason}")
        self._send_single_bet_fire_and_forget(signal, next_entry, bet_value)
        await self._persist_and_publish(signal)

    def _ensure_subtracao_state(self, signal: Signal) -> dict:
        if signal.history is None:
            signal.history = []
        if signal.snapshot is None:
            signal.snapshot = []
        if signal.log is None:
            signal.log = []
        if signal.temp_state is None or not isinstance(signal.temp_state, dict):
            signal.temp_state = {}

        state = signal.temp_state
        state.setdefault("gatilho", (signal.triggers or [None])[0])
        state.setdefault("n_prev", None)
        state.setdefault("grupo", "")
        state.setdefault("alvo_sub", "")
        state.setdefault("entradas_feitas", 0)
        state.setdefault("pausa_restante", 0)
        state.setdefault("ref_escada", state.get("gatilho"))
        state.setdefault("historico_pausas", [])
        state.setdefault("resultados_girados", [])
        state.setdefault("entry_armed", False)
        state.setdefault("current_entry", None)
        state.setdefault("current_bet_value", None)

        entry_values = state.get("entry_bet_values")
        if not isinstance(entry_values, list) or not entry_values:
            entry_values = self.subtracao_entry_values.copy()
        else:
            normalized_values = []
            for value in entry_values:
                try:
                    normalized_values.append(float(value))
                except (TypeError, ValueError):
                    continue
            entry_values = normalized_values or self.subtracao_entry_values.copy()

        max_entries = signal.gales or len(self.subtracao_entry_values)
        while len(entry_values) < max_entries:
            entry_values.append(entry_values[-1] if entry_values else self.default_bet_value)
        state["entry_bet_values"] = entry_values[:max_entries]

        signal.attempts = int(state["entradas_feitas"])
        return state

    def _get_entry_bet_value(self, state: dict, entry_number: int) -> float:
        values = state.get("entry_bet_values") or self.subtracao_entry_values
        index = max(0, entry_number - 1)
        if index >= len(values):
            return float(values[-1])
        return float(values[index])

    @staticmethod
    def _verificar_turbulencia(atual: int, referencia: int | None) -> bool:
        if not isinstance(atual, int) or not isinstance(referencia, int):
            return False
        if atual == 0 or referencia == 0:
            return False
        return abs(atual - referencia) <= 3 or (atual % 10 == referencia % 10)

    def _build_pause_message(self, state: dict) -> str:
        return (
            f"⏸ Em pausa por turbulencia | "
            f"restam {state['pausa_restante']} giro(s) | "
            f"gatilho {state.get('gatilho')} | alvo {state.get('alvo_sub')}"
        )

    def _build_final_message(
        self,
        *,
        state: dict,
        result: str,
        hit_number: int | None,
        current_entry: int,
    ) -> str:
        base = (
            f"{result} | gatilho {state.get('gatilho')} | anterior {state.get('n_prev')} | "
            f"{state.get('grupo')} -> {state.get('alvo_sub')}"
        )
        if hit_number is not None:
            return f"{base} | numero {hit_number} | entrada E{current_entry}"
        return f"{base} | esgotou E{current_entry}"


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
        if not self.auto_bet_enabled:
            logger.warning(
                "[AUTO BOT] envio desativado | signal_id=%s | gale=%s | valor=%.2f",
                signal.id,
                gale_number,
                bet_value,
            )
            return
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

        if not self.auto_bet_enabled:
            logger.warning(
                "[AUTO BOT] envio legado desativado | signal_id=%s | gales=%s",
                signal.id,
                gales,
            )
            return

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
        if not self.auto_bet_enabled:
            logger.warning(
                "[BET API] envio desativado | signal_id=%s | gale=%s | valor=%.2f",
                signal.id,
                gale_number,
                valor,
            )
            return {"success": False, "skipped": True, "reason": "auto_bet_disabled"}

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
                "spins_required": signal.spins_required,
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
            if signal.status in self.FINAL_STATUSES:
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

        
    



        

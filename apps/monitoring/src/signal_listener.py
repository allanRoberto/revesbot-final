# src/signal_listener.py
import asyncio
import json
import logging
import redis.asyncio as aioredis
from pydantic import ValidationError

from .config import settings
from .processor_monitoring import SignalProcessor

logger = logging.getLogger(__name__)

# Streams e Consumer Group
STREAM_NEW_SIGNALS = "streams:signals:new"
STREAM_UPDATES = "streams:signals:updates"
CONSUMER_GROUP = "signal_processors"
MAX_ACTIVE_SIGNALS = 10000

class SignalListener:
    def __init__(self):
        self.redis = aioredis.from_url(settings.signals_redis_url, decode_responses=True)
        self.results_redis = aioredis.from_url(settings.results_redis_url, decode_responses=True)
        self._sem = asyncio.Semaphore(MAX_ACTIVE_SIGNALS)
        self._tasks: dict[str, asyncio.Task] = {}
        self._queues: dict[str, asyncio.Queue] = {}
        self._signals: dict[str, dict] = {}
        self.processor = SignalProcessor()
        self.consumer_name = f"processor_{int(asyncio.get_event_loop().time())}"
        self._invalid_contract_counts: dict[str, int] = {}

    @staticmethod
    def _safe_redis_url(url: str) -> str:
        if "@" not in url:
            return url
        _head, tail = url.split("@", 1)
        return "***@" + tail

    def _warn_invalid_contract(self, contract: str, reason: str, context: str = "") -> None:
        key = f"{contract}:{reason}"
        count = self._invalid_contract_counts.get(key, 0) + 1
        self._invalid_contract_counts[key] = count
        if count <= 5 or count % 100 == 0:
            ctx = f" ({context})" if context else ""
            logger.warning("[redis:%s] payload descartado: %s%s", contract, reason, ctx)

    @staticmethod
    def _coerce_int_safe(value):
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            text = value.strip()
            if text and (text.isdigit() or (text.startswith("-") and text[1:].isdigit())):
                try:
                    return int(text)
                except ValueError:
                    return None
        return None

    def _parse_json_object(self, raw_data, contract: str, context: str = ""):
        try:
            data = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
        except json.JSONDecodeError:
            self._warn_invalid_contract(contract, "json_invalido", context)
            return None

        if not isinstance(data, dict):
            self._warn_invalid_contract(contract, "payload_nao_dict", context)
            return None
        return data

    def _normalize_result_event(self, raw_data):
        contract = settings.result_channel
        data = self._parse_json_object(raw_data, contract)
        if not data:
            return None

        slug = data.get("slug") or data.get("roulette_id")
        if not isinstance(slug, str) or not slug.strip():
            self._warn_invalid_contract(contract, "slug_ausente")
            return None
        slug = slug.strip()

        raw_number = data.get("result")
        if raw_number is None:
            raw_number = data.get("value", data.get("number"))
        number = self._coerce_int_safe(raw_number)
        if number is None:
            self._warn_invalid_contract(contract, "result_invalido")
            return None

        return slug, number

    def _normalize_new_signal_stream_fields(self, message_id: str, fields):
        contract = STREAM_NEW_SIGNALS
        if not isinstance(fields, dict):
            self._warn_invalid_contract(contract, "envelope_nao_dict", f"id={message_id}")
            return None

        signal_data = fields.get("data")
        if signal_data is None:
            self._warn_invalid_contract(contract, "campo_data_ausente", f"id={message_id}")
            return None

        signal = self._parse_json_object(signal_data, contract, f"id={message_id}")
        if not signal:
            return None

        signal_id_raw = fields.get("signal_id")
        if signal_id_raw is None:
            signal_id_raw = signal.get("id")

        signal_id = str(signal_id_raw).strip() if signal_id_raw is not None else ""
        if not signal_id:
            self._warn_invalid_contract(contract, "signal_id_ausente", f"id={message_id}")
            return None

        status = fields.get("status", signal.get("status"))
        if status is not None and not isinstance(status, str):
            self._warn_invalid_contract(contract, "status_invalido", f"id={message_id}")
            status = None

        return signal_id, signal, status

    async def _ensure_consumer_groups(self):
        """Cria consumer groups se não existirem"""
        for stream in [STREAM_NEW_SIGNALS, STREAM_UPDATES]:
            try:
                await self.redis.xgroup_create(
                    stream,
                    CONSUMER_GROUP,
                    id='0',
                    mkstream=True
                )
                logger.info(f"Consumer group '{CONSUMER_GROUP}' criado para stream '{stream}'")
            except Exception as e:
                if 'BUSYGROUP' in str(e):
                    logger.info(f"Consumer group já existe para '{stream}'")
                else:
                    logger.error(f"Erro ao criar consumer group: {e}")

    async def _consume_new_signals(self):
        """Consome novos sinais do stream"""
        logger.info(f"Iniciando consumo de novos sinais (Consumer: {self.consumer_name})")
        
        while True:
            try:
                # Ler mensagens do stream usando consumer group
                results = await self.redis.xreadgroup(
                    CONSUMER_GROUP,
                    self.consumer_name,
                    {STREAM_NEW_SIGNALS: '>'},
                    count=100,
                    block=5000
                )
                
                if not results:
                    continue
                
                for stream, messages in results:
                    for message_id, fields in messages:
                        signal_id = "-"
                        acquired = False
                        task_registered = False
                        try:
                            normalized = self._normalize_new_signal_stream_fields(message_id, fields)
                            if not normalized:
                                await self.redis.xack(STREAM_NEW_SIGNALS, CONSUMER_GROUP, message_id)
                                continue
                            signal_id, signal, _status = normalized
                            
                            # Verificar se já está sendo monitorado
                            if signal_id in self._tasks:
                                logger.debug(f"Sinal {signal_id} já está sendo monitorado")
                                await self.redis.xack(STREAM_NEW_SIGNALS, CONSUMER_GROUP, message_id)
                                continue

                            # Iniciar monitoramento
                            try:
                                await self._sem.acquire()
                                acquired = True
                                queue = asyncio.Queue()
                                self._queues[signal_id] = queue
                                self._signals[signal_id] = signal
                                startup_future = asyncio.get_running_loop().create_future()
                                task = asyncio.create_task(
                                    self.processor.monitor_single_signal_queue(
                                        signal,
                                        queue,
                                        startup_future=startup_future,
                                    )
                                )
                                self._tasks[signal_id] = task
                                task_registered = True
                                task.add_done_callback(
                                    lambda t, sid=signal_id: self._on_task_done(sid)
                                )
                                # ACK somente após startup essencial confirmado.
                                try:
                                    await startup_future
                                except ValidationError as e:
                                    logger.warning(
                                        "[STREAM ACK] ACK por falha definitiva de modelo "
                                        "signal_id=%s message_id=%s motivo=%s",
                                        signal_id,
                                        message_id,
                                        e,
                                    )
                                    await self.redis.xack(STREAM_NEW_SIGNALS, CONSUMER_GROUP, message_id)
                                    continue
                                except Exception as e:
                                    logger.error(
                                        "[STREAM ACK] sem ACK por falha inesperada de startup "
                                        "signal_id=%s message_id=%s motivo=%s",
                                        signal_id,
                                        message_id,
                                        e,
                                        exc_info=True,
                                    )
                                    continue

                                await self.redis.xack(STREAM_NEW_SIGNALS, CONSUMER_GROUP, message_id)
                            except Exception:
                                if acquired and not task_registered:
                                    self._sem.release()
                                if not task_registered:
                                    self._queues.pop(signal_id, None)
                                    self._signals.pop(signal_id, None)
                                raise
                            
                        except Exception as e:
                            logger.error(
                                "[STREAM ACK] sem ACK por falha inesperada "
                                "signal_id=%s message_id=%s motivo=%s",
                                signal_id,
                                message_id,
                                e,
                                exc_info=True,
                            )
                
            except Exception as e:
                logger.error(f"Erro no loop de consumo: {e}", exc_info=True)
                await asyncio.sleep(5)


    async def _monitor_pending_messages(self):
        """Monitora mensagens pendentes e reprocessa se necessário"""
        while True:
            try:
                await asyncio.sleep(60)
                
                pending = await self.redis.xpending_range(
                    STREAM_NEW_SIGNALS,
                    CONSUMER_GROUP,
                    min='-',
                    max='+',
                    count=100
                )
                
                if pending:
                    logger.info(f"Encontradas {len(pending)} mensagens pendentes")
                    
                    for msg in pending:
                        message_id = msg['message_id']
                        idle_time = msg['time_since_delivered']
                        
                        if idle_time > 300000:
                            logger.warning(f"Reclamando mensagem pendente: {message_id}")
                            
                            await self.redis.xclaim(
                                STREAM_NEW_SIGNALS,
                                CONSUMER_GROUP,
                                self.consumer_name,
                                min_idle_time=300000,
                                message_ids=[message_id]
                            )
                
            except Exception as e:
                logger.error(f"Erro ao monitorar mensagens pendentes: {e}")

    def _on_task_done(self, signal_id: str):
        """Callback quando uma task de monitoramento termina"""
        self._sem.release()
        self._tasks.pop(signal_id, None)
        self._queues.pop(signal_id, None)
        self._signals.pop(signal_id, None)
        logger.info(f"Task finalizada: {signal_id}")

    async def _listen_results(self):
        """Escuta resultados e distribui para as filas dos sinais ativos."""
        pubsub = self.results_redis.pubsub()
        await pubsub.subscribe(settings.result_channel)
        logger.info("Escutando resultados em %s", settings.result_channel)

        try:
            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message is None:
                    await asyncio.sleep(0.05)
                    continue

                normalized = self._normalize_result_event(message.get("data"))
                if not normalized:
                    continue
                slug, number = normalized

                for signal_id, signal in list(self._signals.items()):
                    if signal.get("roulette_id") != slug:
                        continue
                    queue = self._queues.get(signal_id)
                    if queue:
                        try:
                            queue.put_nowait(number)
                        except Exception:
                            continue
        finally:
            await pubsub.unsubscribe(settings.result_channel)

    async def start(self):
        """Inicia o listener"""
        logger.info(
            "Iniciando Signal Listener | redis_sinais=%s | redis_resultados=%s | canal=%s",
            self._safe_redis_url(settings.signals_redis_url),
            self._safe_redis_url(settings.results_redis_url),
            settings.result_channel,
        )
        
        try:
            # Criar consumer groups
            await self._ensure_consumer_groups()
            
            # Iniciar consumers em paralelo
            await asyncio.gather(
                self._consume_new_signals(),
                self._listen_results(),
            )
            
        except Exception as e:
            logger.error(f"Erro fatal no listener: {e}", exc_info=True)
            raise
        finally:
            await self.redis.close()
            await self.results_redis.close()


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    
    listener = SignalListener()
    
    try:
        await listener.start()
    except KeyboardInterrupt:
        logger.info("Encerrando listener...")
    except Exception as e:
        logger.error(f"Erro fatal: {e}", exc_info=True)
    finally:
        pass


if __name__ == "__main__":
    asyncio.run(main())

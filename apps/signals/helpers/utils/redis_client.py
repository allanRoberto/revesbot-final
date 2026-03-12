import logging
import redis

from core.redis_connections import get_sync_signals_redis_client, get_signals_redis_url


logger = logging.getLogger(__name__)


# Crie uma instância do cliente Redis
try:
    r = get_sync_signals_redis_client()
    r.ping()  # Tenta se conectar ao servidor Redis
    logger.info("Conexao com Redis de sinais estabelecida em %s", get_signals_redis_url())
except redis.exceptions.ConnectionError as e:
    logger.error("Erro ao conectar ao Redis de sinais: %s", e)

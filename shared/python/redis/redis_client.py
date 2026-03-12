# from dotenv import load_dotenv
# import os
# from upstash_redis import Redis

# load_dotenv()

# REDIS_HOST = os.getenv("REDIS_HOST")
# REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")


# redis = Redis(url=REDIS_HOST, token=REDIS_PASSWORD) 
from dotenv import load_dotenv
import logging
import os
import redis

load_dotenv()
redis_host = os.getenv("REDIS_CONNECT")
logger = logging.getLogger(__name__)


# Crie uma instância do cliente Redis
try:
    r = redis.from_url(redis_host)
    r.ping()  # Tenta se conectar ao servidor Redis
    logger.info("Conexao com Redis estabelecida em %s", redis_host)
except redis.exceptions.ConnectionError as e:
    logger.error("Erro ao conectar ao Redis: %s", e)

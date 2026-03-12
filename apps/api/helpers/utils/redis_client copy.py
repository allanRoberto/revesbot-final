# from dotenv import load_dotenv
# import os
# from upstash_redis import Redis

# load_dotenv()

# REDIS_HOST = os.getenv("REDIS_HOST")
# REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")


# redis = Redis(url=REDIS_HOST, token=REDIS_PASSWORD) 
from dotenv import load_dotenv
import redis
import os

load_dotenv()



redis_host = os.environ.get("REDIS_CONNECT", "")


# Crie uma instância do cliente Redis
try:
    r = redis.from_url(redis_host)
    r.ping()  # Tenta se conectar ao servidor Redis
    print(f"Conexão com Redis estabelecida em {redis_host}")
except redis.exceptions.ConnectionError as e:
    print(f"Erro ao conectar ao Redis: {e}")
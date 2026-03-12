# from dotenv import load_dotenv
# import os
# from upstash_redis import Redis

# load_dotenv()

# REDIS_HOST = os.getenv("REDIS_HOST")
# REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")


# redis = Redis(url=REDIS_HOST, token=REDIS_PASSWORD) 
import os
from urllib.parse import quote

from dotenv import load_dotenv
import redis

load_dotenv()



def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _build_url_from_parts(host: str, port: int, db: int, user: str = "", password: str = "") -> str:
    auth = ""
    if password:
        encoded_password = quote(password, safe="")
        if user:
            encoded_user = quote(user, safe="")
            auth = f"{encoded_user}:{encoded_password}@"
        else:
            auth = f":{encoded_password}@"
    return f"redis://{auth}{host}:{port}/{db}"


redis_host = (os.getenv("REDIS_SIGNALS_CONNECT") or os.getenv("REDIS_CONNECT") or "").strip()
if not redis_host:
    host = (os.getenv("REDIS_SIGNALS_HOST") or os.getenv("REDIS_HOST") or "127.0.0.1").strip()
    port = _env_int("REDIS_SIGNALS_PORT", _env_int("REDIS_PORT", 6379))
    db = _env_int("REDIS_SIGNALS_DB", _env_int("REDIS_DB", 0))
    user = (os.getenv("REDIS_SIGNALS_USER") or os.getenv("REDIS_USER") or "").strip()
    password = (os.getenv("REDIS_SIGNALS_PASSWORD") or os.getenv("REDIS_PASSWORD") or "").strip()
    redis_host = _build_url_from_parts(host=host, port=port, db=db, user=user, password=password)


# Crie uma instância do cliente Redis
try:
    r = redis.from_url(redis_host)
    r.ping()  # Tenta se conectar ao servidor Redis
    print(f"Conexão com Redis estabelecida em {redis_host}")
except redis.exceptions.ConnectionError as e:
    print(f"Erro ao conectar ao Redis: {e}")

# core/db.py
import certifi
import pytz
import redis
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient

from api.core.config import settings

# ─── Conexão MongoDB / Motor ───────────────────────────────────────────────────
MONGO_URL = settings.mongo_url
mongo_client = AsyncIOMotorClient(
    MONGO_URL,
    tls=True,
    tlsCAFile=certifi.where()
)
mongo_db     = mongo_client["roleta_db"]
history_coll = mongo_db["history"]
agent_sessions_coll = mongo_db["agent_sessions"]
agent_templates_coll = mongo_db["agent_templates"]

# Função utilitária (mantida aqui se outros módulos precisarem)
def format_timestamp_br(timestamp: int) -> str:
    tz = pytz.timezone("America/Sao_Paulo")
    dt = datetime.fromtimestamp(timestamp, tz)
    return dt.strftime("%d/%m/%Y %H:%M:%S")

predictions_norm_coll = mongo_db["predictions_normalized"]

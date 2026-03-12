# src/config.py
"""
Configuração da aplicação via variáveis de ambiente, sem validações externas.
"""
import os

from dotenv import load_dotenv
from src.core.redis_connections import get_results_redis_url, get_signals_redis_url


# ─── Config ────────────────────────────────────────────────────────────────────
load_dotenv()

class Settings:
    """
    Carrega configurações diretamente de variáveis de ambiente.
    """
    def __init__(self):

        mode_simulator = os.getenv("SIMULATOR", "false").lower() == "true"

        print("modo simulador", mode_simulator)

        if mode_simulator : 
            self.result_channel = os.getenv("RESULT_CHANNEL", "new_result_simulate")   

        else :
            self.result_channel = os.getenv("RESULT_CHANNEL", "new_result")   
        
        self.signals_redis_url = get_signals_redis_url()
        self.results_redis_url = get_results_redis_url()
        # Compatibilidade com código legado que ainda lê settings.redis_url
        self.redis_url = self.signals_redis_url
        self.update_channel = os.getenv("UPDATE_CHANNEL", "signal_update")
        self.backoff_max = int(os.getenv("BACKOFF_MAX", "60"))
        self.metrics_port = int(os.getenv("METRICS_PORT", "8090"))

# Instância global de configurações
settings = Settings()

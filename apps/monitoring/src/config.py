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
        self.api_base_url = (
            os.getenv("SUGGESTION_MONITOR_API_BASE_URL")
            or os.getenv("BASE_URL_API")
            or "http://localhost:8081"
        ).rstrip("/")
        self.mongo_url = (os.getenv("MONGO_URL") or os.getenv("mongo_url") or "").strip()
        self.mongo_db_name = (os.getenv("MONGO_DB") or "roleta_db").strip() or "roleta_db"
        self.suggestion_monitor_enabled = os.getenv("SUGGESTION_MONITOR_ENABLED", "true").lower() == "true"
        self.suggestion_monitor_roulette_id = (
            os.getenv("SUGGESTION_MONITOR_ROULETTE_ID", "pragmatic-auto-roulette").strip()
            or "pragmatic-auto-roulette"
        )
        self.suggestion_monitor_max_numbers = int(os.getenv("SUGGESTION_MONITOR_MAX_NUMBERS", "37"))
        self.suggestion_monitor_shadow_compare_enabled = False
        self.suggestion_monitor_shadow_compare_max_numbers = int(
            os.getenv("SUGGESTION_MONITOR_SHADOW_COMPARE_MAX_NUMBERS", "32")
        )
        self.suggestion_monitor_history_window = int(os.getenv("SUGGESTION_MONITOR_HISTORY_WINDOW", "200"))
        self.suggestion_monitor_fast_forward_on_backlog = (
            os.getenv("SUGGESTION_MONITOR_FAST_FORWARD_ON_BACKLOG", "true").lower() == "true"
        )
        self.suggestion_monitor_max_backlog_results = int(
            os.getenv("SUGGESTION_MONITOR_MAX_BACKLOG_RESULTS", "300")
        )
        self.suggestion_monitor_poll_interval_seconds = float(
            os.getenv("SUGGESTION_MONITOR_POLL_INTERVAL_SECONDS", "5")
        )
        self.suggestion_monitor_api_timeout_seconds = float(
            os.getenv("SUGGESTION_MONITOR_API_TIMEOUT_SECONDS", "20")
        )
        self.suggestion_monitor_simple_path = (
            os.getenv("SUGGESTION_MONITOR_SIMPLE_PATH", "/api/patterns/simple-suggestion").strip()
            or "/api/patterns/simple-suggestion"
        )
        self.suggestion_monitor_optimized_max_numbers = int(
            os.getenv("SUGGESTION_MONITOR_OPTIMIZED_MAX_NUMBERS", "37")
        )
        self.suggestion_monitor_base_weight = float(
            os.getenv("SUGGESTION_MONITOR_BASE_WEIGHT", "0.5")
        )
        self.suggestion_monitor_optimized_weight = float(
            os.getenv("SUGGESTION_MONITOR_OPTIMIZED_WEIGHT", "0.5")
        )
        self.suggestion_monitor_siege_window = int(
            os.getenv("SUGGESTION_MONITOR_SIEGE_WINDOW", "6")
        )
        self.suggestion_monitor_siege_min_occurrences = int(
            os.getenv("SUGGESTION_MONITOR_SIEGE_MIN_OCCURRENCES", "3")
        )
        self.suggestion_monitor_siege_min_streak = int(
            os.getenv("SUGGESTION_MONITOR_SIEGE_MIN_STREAK", "2")
        )
        self.suggestion_monitor_siege_veto_relief = float(
            os.getenv("SUGGESTION_MONITOR_SIEGE_VETO_RELIEF", "0.4")
        )
        self.suggestion_monitor_block_bets_enabled = (
            os.getenv("SUGGESTION_MONITOR_BLOCK_BETS_ENABLED", "true").lower() == "true"
        )
        self.suggestion_monitor_inversion_enabled = (
            os.getenv("SUGGESTION_MONITOR_INVERSION_ENABLED", "true").lower() == "true"
        )
        self.suggestion_monitor_inversion_context_window = int(
            os.getenv("SUGGESTION_MONITOR_INVERSION_CONTEXT_WINDOW", "15")
        )
        self.suggestion_monitor_inversion_penalty_factor = float(
            os.getenv("SUGGESTION_MONITOR_INVERSION_PENALTY_FACTOR", "0.3")
        )
        self.suggestion_monitor_weight_profile_id = (
            os.getenv("SUGGESTION_MONITOR_WEIGHT_PROFILE_ID", "").strip() or None
        )
        self.suggestion_monitor_protected_mode_enabled = (
            os.getenv("SUGGESTION_MONITOR_PROTECTED_MODE_ENABLED", "false").lower() == "true"
        )
        self.suggestion_monitor_protected_suggestion_size = int(
            os.getenv("SUGGESTION_MONITOR_PROTECTED_SUGGESTION_SIZE", "35")
        )
        self.suggestion_monitor_protected_swap_enabled = (
            os.getenv("SUGGESTION_MONITOR_PROTECTED_SWAP_ENABLED", "false").lower() == "true"
        )
        self.suggestion_monitor_cold_count = int(
            os.getenv("SUGGESTION_MONITOR_COLD_COUNT", "18")
        )
        self.suggestion_monitor_runtime_overrides = {
            "siege_number_boost": {
                "window": int(self.suggestion_monitor_siege_window),
                "min_occurrences": int(self.suggestion_monitor_siege_min_occurrences),
                "min_streak": int(self.suggestion_monitor_siege_min_streak),
            }
        }
        self.suggestion_monitor_control_channel = (
            os.getenv("SUGGESTION_MONITOR_CONTROL_CHANNEL", "suggestion_monitor_control").strip()
            or "suggestion_monitor_control"
        )

# Instância global de configurações
settings = Settings()

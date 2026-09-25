try:
    from pydantic_settings import BaseSettings, SettingsConfigDict

    class Settings(BaseSettings):
        mongo_url: str | None = None
        mongo_database: str = "roleta_db"
        pixgo_mongo_url: str | None = None
        pixgo_mongo_database: str = "roleta_db"
        redis_connect: str | None = None
        port: int = 8080
        bot_automation_enabled: bool = False
        bot_api_url: str = "http://localhost:3000/api/bet"
        bot_health_url: str = "http://localhost:3000/health"
        pattern_metrics_enabled: bool = False
        pixgo_api_key: str | None = None
        pixgo_webhook_secret: str | None = None
        pixgo_base_url: str = "https://pixgo.org/api/v1"
        openrouter_api_key: str | None = None
        openrouter_model: str = "typesafe/jev-1.13"
        jev_max_history: int = 10_000
        jev_max_body_bytes: int = 262_144
        jev_results_dir: str = "resultados/jev"
        jev_backtest_max_calls: int = 1_000
        jev_input_price_per_million: float = 0.042
        jev_panel_user: str | None = None
        jev_panel_password: str | None = None

        model_config = SettingsConfigDict(
            env_file=".env",
            extra="ignore",
        )

except Exception:  # pragma: no cover - fallback for older envs
    from pydantic import BaseSettings

    class Settings(BaseSettings):
        mongo_url: str | None = None
        mongo_database: str = "roleta_db"
        pixgo_mongo_url: str | None = None
        pixgo_mongo_database: str = "roleta_db"
        redis_connect: str | None = None
        port: int = 8080
        bot_automation_enabled: bool = False
        bot_api_url: str = "http://localhost:3000/api/bet"
        bot_health_url: str = "http://localhost:3000/health"
        pattern_metrics_enabled: bool = False
        pixgo_api_key: str | None = None
        pixgo_webhook_secret: str | None = None
        pixgo_base_url: str = "https://pixgo.org/api/v1"
        openrouter_api_key: str | None = None
        openrouter_model: str = "typesafe/jev-1.13"
        jev_max_history: int = 10_000
        jev_max_body_bytes: int = 262_144
        jev_results_dir: str = "resultados/jev"
        jev_backtest_max_calls: int = 1_000
        jev_input_price_per_million: float = 0.042
        jev_panel_user: str | None = None
        jev_panel_password: str | None = None

        class Config:
            env_file = ".env"
            env_prefix = ""
            extra = "ignore"


settings = Settings()

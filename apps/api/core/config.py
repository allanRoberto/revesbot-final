try:
    from pydantic_settings import BaseSettings, SettingsConfigDict

    class Settings(BaseSettings):
        mongo_url: str | None = None
        redis_connect: str | None = None
        port: int = 8080
        bot_automation_enabled: bool = False
        bot_api_url: str = "http://localhost:3000/api/bet"
        bot_health_url: str = "http://localhost:3000/health"
        pattern_metrics_enabled: bool = False

        model_config = SettingsConfigDict(
            env_file=".env",
            extra="ignore",
        )

except Exception:  # pragma: no cover - fallback for older envs
    from pydantic import BaseSettings

    class Settings(BaseSettings):
        mongo_url: str | None = None
        redis_connect: str | None = None
        port: int = 8080
        bot_automation_enabled: bool = False
        bot_api_url: str = "http://localhost:3000/api/bet"
        bot_health_url: str = "http://localhost:3000/health"
        pattern_metrics_enabled: bool = False

        class Config:
            env_file = ".env"
            env_prefix = ""
            extra = "ignore"


settings = Settings()

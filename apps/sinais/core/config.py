"""Configuração do app de sinais (pydantic-settings, lê do .env do repo root)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Banco (mesmo cluster da API interna; usamos history só-leitura)
    mongo_url: str | None = None

    # Clerk (login)
    clerk_secret_key: str | None = None
    clerk_publishable_key: str | None = None
    clerk_webhook_secret: str | None = None
    # Opcional: força a URL do JWKS. Se vazio, derivamos do issuer do token.
    clerk_jwks_url: str | None = None
    # Opcional: azp/origens autorizadas (separadas por vírgula) para validar o token.
    clerk_authorized_parties: str | None = None

    # Stripe (compra de créditos) — chaves já existem no .env
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None

    # Servidor / URLs públicas
    sinais_port: int = 8090
    sinais_app_url: str = "http://localhost:8091"

    # Regras de produto
    sinais_roulette_ids: str = (
        "pragmatic-brazilian-roulette,"
        "pragmatic-auto-roulette,"
        "pragmatic-immersive-roulette-deluxe"
    )
    signup_credits: int = 5
    history_window: int = 300   # últimos N números usados para gerar a entrada
    attempts: int = 3           # tentativas (janela de apuração)
    entry_numbers: int = 12     # tamanho da entrada
    settlement_poll_seconds: float = 2.0

    # Pacotes de crédito (preço progressivo por usuário)
    credit_pack_size: int = 10          # créditos por compra
    credit_base_price: float = 1.00     # R$ por crédito na 1ª compra
    credit_price_increment: float = 0.25  # R$ somados ao crédito a cada compra
    currency: str = "brl"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def allowed_roulettes(self) -> list[str]:
        return [s.strip() for s in (self.sinais_roulette_ids or "").split(",") if s.strip()]

    @property
    def allowed_entry_sizes(self) -> list[int]:
        return [8, 12, 18, 26]

    @property
    def authorized_parties(self) -> list[str]:
        raw = self.clerk_authorized_parties or ""
        return [s.strip() for s in raw.split(",") if s.strip()]


settings = Settings()

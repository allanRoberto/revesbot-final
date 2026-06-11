"""Preço progressivo dos pacotes de crédito.

Cada compra é um pacote fixo de `credit_pack_size` créditos. O preço por
crédito sobe R$`credit_price_increment` a cada compra que o usuário já fez:

    preço_crédito(n) = base + incremento * n        (n = compras anteriores)

Ex.: base 1,00 / incremento 0,25 → 1,00, 1,25, 1,50, 1,75, ...
"""

from sinais.core.config import settings


def unit_price(purchase_count: int) -> float:
    """Preço (R$) de 1 crédito para quem já fez `purchase_count` compras."""
    n = max(0, int(purchase_count))
    return round(settings.credit_base_price + settings.credit_price_increment * n, 2)


def pack_total(purchase_count: int) -> float:
    """Preço (R$) do pacote inteiro (`credit_pack_size` créditos)."""
    return round(unit_price(purchase_count) * settings.credit_pack_size, 2)


def unit_price_cents(purchase_count: int) -> int:
    """Preço de 1 crédito em centavos (para o Stripe)."""
    return int(round(unit_price(purchase_count) * 100))


def offer(purchase_count: int) -> dict:
    """Resumo da próxima compra, para a API/UI."""
    return {
        "credits": settings.credit_pack_size,
        "unit_price": unit_price(purchase_count),
        "total": pack_total(purchase_count),
        "currency": settings.currency,
        "purchase_count": int(purchase_count),
    }

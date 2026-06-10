"""Nomes amigáveis das mesas suportadas."""

ROULETTE_NAMES = {
    "pragmatic-brazilian-roulette": "Brazilian Roulette",
    "pragmatic-auto-roulette": "Auto Roulette",
    "pragmatic-immersive-roulette-deluxe": "Immersive Roulette Deluxe",
}


def display_name(slug: str) -> str:
    return ROULETTE_NAMES.get(slug, slug)

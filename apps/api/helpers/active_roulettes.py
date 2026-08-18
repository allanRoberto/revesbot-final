from __future__ import annotations


ACTIVE_ROULETTES = (
    {"id": "237", "slug": "pragmatic-brazilian-roulette", "name": "Brazilian Roulette", "url": "https://lotogreen.bet.br/play/450"},
    {"id": "204", "slug": "pragmatic-mega-roulette", "name": "Mega Roulette", "url": "https://lotogreen.bet.br/play/550"},
    {"id": "225", "slug": "pragmatic-auto-roulette", "name": "Auto Roulette", "url": "https://lotogreen.bet.br/play/373"},
    {"id": "292", "slug": "pragmatic-immersive-roulette-deluxe", "name": "Immersive Roulette Deluxe", "url": "https://lotogreen.bet.br/play/8261"},
    {"id": "2501", "slug": "pragmatic-table-2501", "name": "Crystal Roulette"},
    {"id": "545", "slug": "pragmatic-vip-roulette", "name": "VIP Roulette", "url": "https://lotogreen.bet.br/play/457"},
    {"id": "270", "slug": "pragmatic-table-270", "name": "Fortune Roulette"},
    {"id": "12501", "slug": "pragmatic-table-12501", "name": "Speed Roulette Latina"},
    {"id": "28301", "slug": "pragmatic-table-28301", "name": "Privé Lounge Roulette Deluxe"},
    {"id": "28201", "slug": "pragmatic-table-28201", "name": "Privé Lounge Roulette"},
    {"id": "266", "slug": "pragmatic-vip-auto-roulette", "name": "VIP Auto Roulette", "url": "https://lotogreen.bet.br/play/457"},
    {"id": "230", "slug": "pragmatic-roulete-3", "name": "Roulette 3", "url": "https://lotogreen.bet.br/play/476"},
    {"id": "211", "slug": "pragmatic-table-211", "name": "Lucky 6 Roulette", "url": "https://lotogreen.bet.br/play/6477"},
    {"id": "203", "slug": "pragmatic-speed-roulette-1", "name": "Speed Roulette 1", "url": "https://lotogreen.bet.br/play/556"},
    {"id": "206", "slug": "pragmatic-roulette-macao", "name": "Roulette Macao", "url": "https://lotogreen.bet.br/play/552"},
    {"id": "287", "slug": "pragmatic-mega-roulette-brazilian", "name": "Brazilian Mega Roulette", "url": "https://lotogreen.bet.br/play/6478"},
)

ACTIVE_ROULETTE_BY_SLUG = {
    item["slug"]: dict(item) for item in ACTIVE_ROULETTES
}
ACTIVE_ROULETTE_SLUGS = tuple(item["slug"] for item in ACTIVE_ROULETTES)


__all__ = [
    "ACTIVE_ROULETTES",
    "ACTIVE_ROULETTE_BY_SLUG",
    "ACTIVE_ROULETTE_SLUGS",
]

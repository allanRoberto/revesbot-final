from __future__ import annotations

from apps.monitoring.patterns.core.contracts import LoadedPattern, PatternDefinition

from .engine import LastHopePattern


SCHEDULES = {
    "pragmatic-auto-mega-roulette": (23, 20, 21, 5),
    "pragmatic-auto-roulette": (5, 1, 9, 6),
    "pragmatic-brazilian-roulette": (2, 20, 8, 6),
    "pragmatic-german-roulette": (22, 13, 14, 2),
    "pragmatic-immersive-roulette-deluxe": (19, 4, 13, 10),
    "pragmatic-korean-roulette": (14, 10, 17, 16),
    "pragmatic-mega-roulette": (9, 4, 15, 16),
    "pragmatic-mega-roulette-brazilian": (15, 7, 10, 22),
    "pragmatic-romanian-roulette": (5, 3, 10, 23),
    "pragmatic-roulete-3": (19, 9, 11, 13),
    "pragmatic-roulette-1": (4, 11, 20, 14),
    "pragmatic-roulette-2": (19, 3, 11, 6),
    "pragmatic-roulette-italia-tricolore": (1, 12, 9, 7),
    "pragmatic-roulette-italian": (18, 8, 14, 0),
    "pragmatic-roulette-macao": (19, 12, 0, 16),
    "pragmatic-russian-roulette": (7, 9, 3, 8),
    "pragmatic-speed-auto-roulette": (20, 13, 18, 8),
    "pragmatic-speed-roulette-1": (19, 23, 16, 10),
    "pragmatic-speed-roulette-2": (4, 14, 13, 15),
    "pragmatic-turkish-mega-roulette": (10, 21, 8, 15),
    "pragmatic-turkish-roulette": (11, 3, 19, 18),
    "pragmatic-vietnamese-roulette": (6, 5, 16, 9),
    "pragmatic-vip-auto-roulette": (1, 9, 22, 20),
    "pragmatic-vip-roulette": (4, 22, 21, 15),
}


def create_pattern() -> LoadedPattern:
    definition = PatternDefinition(
        key="last_hope",
        name="Last Hope",
        version="v22-gap-variations-mongo-1",
        description="Contexto deslizante de quentes e frios com quatro tentativas.",
        required_history=50,
        history_size=500,
        max_attempts=4,
        roulette_ids=tuple(SCHEDULES),
        schedules=SCHEDULES,
        default_chip_profile=(2.5, 1.5, 1.5, 1.0),
        configuration={"gap_reset_seconds": 300, "source": "MongoDB"},
        ui_schema={
            "accent": "#6d28d9",
            "detail_fields": [
                {"key": "timeframe", "label": "Janela"},
                {"key": "score", "label": "Score", "format": "percent"},
                {"key": "hot_numbers", "label": "Quentes", "format": "numbers"},
                {"key": "cold_numbers", "label": "Frios", "format": "numbers"},
            ],
        },
    )
    return LoadedPattern(definition=definition, engine=LastHopePattern())

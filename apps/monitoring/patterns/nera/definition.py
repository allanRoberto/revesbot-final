from __future__ import annotations

from apps.monitoring.patterns.core.contracts import LoadedPattern, PatternDefinition

from .engine import NeraPattern


SCHEDULES = {
    "pragmatic-auto-mega-roulette": (13, 16, 7, 21),
    "pragmatic-auto-roulette": (13, 12, 10, 2),
    "pragmatic-brazilian-roulette": (16, 17, 1, 21),
    "pragmatic-german-roulette": (5, 22, 23, 18),
    "pragmatic-immersive-roulette-deluxe": (2, 10, 6, 4),
    "pragmatic-korean-roulette": (2, 17, 18),
    "pragmatic-mega-roulette": (0, 21, 19, 3),
    "pragmatic-mega-roulette-brazilian": (19, 5, 0, 6),
    "pragmatic-romanian-roulette": (17, 1, 22, 13),
    "pragmatic-roulete-3": (22, 1, 11, 15),
    "pragmatic-roulette-1": (10, 1, 7, 18),
    "pragmatic-roulette-2": (1, 21, 9),
    "pragmatic-roulette-italia-tricolore": (23, 7, 1, 12),
    "pragmatic-roulette-italian": (17, 2, 7, 16),
    "pragmatic-roulette-macao": (3, 2, 22, 11),
    "pragmatic-russian-roulette": (15, 10, 4, 2),
    "pragmatic-speed-auto-roulette": (5, 0, 18, 4),
    "pragmatic-speed-roulette-1": (18, 8, 15, 17),
    "pragmatic-speed-roulette-2": (7, 20, 8, 9),
    "pragmatic-turkish-mega-roulette": (0, 1, 10, 4),
    "pragmatic-turkish-roulette": (0, 17, 21, 18),
    "pragmatic-vietnamese-roulette": (14, 1, 13, 11),
    "pragmatic-vip-auto-roulette": (6, 9, 14, 8),
    "pragmatic-vip-roulette": (15, 14, 17, 21),
}


def create_pattern() -> LoadedPattern:
    definition = PatternDefinition(
        key="nera",
        name="Nera Alpha",
        version="v846-mongo-1",
        description="Nera Alpha com filtro continuo de contagem e quatro tentativas.",
        required_history=20,
        history_size=500,
        max_attempts=4,
        roulette_ids=tuple(SCHEDULES),
        schedules=SCHEDULES,
        default_chip_profile=(2.5, 1.5, 1.5, 1.0),
        configuration={"gap_reset_seconds": 300, "source": "MongoDB"},
        ui_schema={
            "accent": "#177a5b",
            "detail_fields": [
                {"key": "target", "label": "Alvo"},
                {"key": "target_strength", "label": "Forca"},
                {"key": "trigger_mirror", "label": "Espelho do gatilho"},
            ],
        },
    )
    return LoadedPattern(definition=definition, engine=NeraPattern())

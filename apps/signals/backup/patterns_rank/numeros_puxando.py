"""
Pattern: NUMEROS_PUXANDO

Cria SINAL PAI que controla o ciclo de ativações.
"""

from helpers.roulette_analyzer import RouletteAnalyzer
from helpers.score import get_ranking, nivel_confianca


# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURAÇÕES
# ══════════════════════════════════════════════════════════════════════════════

MAX_ACTIVATIONS = 3
MAX_SPINS = 30
GALES = 3
ANALYSIS_INTERVAL = 30
MIN_HISTORY = 100

_last_analyzed_snapshot = {}


def _should_analyze(slug: str, current_numbers: list) -> bool:
    global _last_analyzed_snapshot
    
    if slug not in _last_analyzed_snapshot:
        return True
    
    last_snapshot = _last_analyzed_snapshot[slug]
    
    try:
        last_first_numbers = last_snapshot[:5]
        for i in range(len(current_numbers) - 5):
            if current_numbers[i:i+5] == last_first_numbers:
                return i >= ANALYSIS_INTERVAL
        return True
    except Exception:
        return True


def _update_snapshot(slug: str, current_numbers: list):
    global _last_analyzed_snapshot
    _last_analyzed_snapshot[slug] = current_numbers[:10].copy()


def process_roulette(roulette, numbers):
    """Cria SINAL PAI."""
    
    slug = roulette['slug']
    
    if len(numbers) < MIN_HISTORY:
        return None
    
    if not _should_analyze(slug, numbers):
        return None
    
    _update_snapshot(slug, numbers)
    
    print(f"[NUMEROS_PUXANDO] Análise para {slug}")
    
    analyzer = RouletteAnalyzer(numbers[:100])
    result = analyzer.analyze()
    
    all_triggers = result.main_triggers

    if 0 not in result.final_group:
        result.final_group.append(0)


    return {
        "roulette_id": slug,
        "roulette_name": roulette["name"],
        "roulette_url": roulette["url"],
        "pattern": "NUMEROS_PUXANDO",
        "triggers": all_triggers,
        "targets": result.final_group,
        "bets": result.final_group,
        "status": "waiting",
        "gales": GALES,
        "passed_spins": 0,
        "spins_required": 0,
        "snapshot": numbers[:1000],
        "score": result.confidence_score,
        "message": f"[PAI] Aguardando gatilho...",
        "tags": ["numeros_puxando", "parent"],
        "temp_state": {
            "is_parent": True,
            "max_activations": MAX_ACTIVATIONS,
            "max_spins": MAX_SPINS,
            "gales_per_child": GALES,
            "current_activation": 0,
            "child_active": False,
            "active_child_id": None,
            "last_win_number": None,
            "children_ids": [],
            "total_wins": 0,
            "total_losses": 0,
        }
    }
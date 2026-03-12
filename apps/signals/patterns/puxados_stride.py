from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Dict, List, Tuple


WINDOW = 3
TOP_WINDOW = 12
TOP_PLUS1 = 3
ANALYSIS_INTERVAL = 3


class RouletteState:
    def __init__(self) -> None:
        self.since_last: int = ANALYSIS_INTERVAL - 1


_states: Dict[str, RouletteState] = {}


def _get_state(slug: str) -> RouletteState:
    if slug not in _states:
        _states[slug] = RouletteState()
    return _states[slug]


def _to_chronological(nums_top_first: List[int]) -> List[int]:
    return list(reversed(nums_top_first))


def _build_prediction_from_history(
    history_seq: List[int],
    target: int,
    window: int,
    top_window: int,
    top_plus1: int,
) -> Tuple[List[int], Counter, Counter]:
    plus1 = Counter()
    win = Counter()

    for i, n in enumerate(history_seq):
        if n != target:
            continue
        after = history_seq[i + 1:i + 1 + window]
        if after:
            plus1[after[0]] += 1
        for x in after:
            win[x] += 1

    suggestion: List[int] = []
    for n, _ in win.most_common(top_window):
        if n not in suggestion:
            suggestion.append(n)
    for n, _ in plus1.most_common(top_plus1):
        if n not in suggestion:
            suggestion.append(n)

    return suggestion, win, plus1


def _confidence_level(base_count: int) -> str:
    if base_count >= 12:
        return "alta"
    if base_count >= 6:
        return "media"
    return "baixa"


def process_roulette(roulette, numbers):
    if not numbers:
        return None

    slug = roulette["slug"]
    state = _get_state(slug)
    state.since_last += 1
    if state.since_last < ANALYSIS_INTERVAL:
        return None
    state.since_last = 0

    seq = _to_chronological(numbers[:2000])
    if len(seq) < 2:
        return None

    target = seq[-1]
    history_seq = seq[:-1]
    base_count = history_seq.count(target)
    confidence = _confidence_level(base_count)

    suggestion, _, _ = _build_prediction_from_history(
        history_seq=history_seq,
        target=target,
        window=WINDOW,
        top_window=TOP_WINDOW,
        top_plus1=TOP_PLUS1,
    )

    if not suggestion:
        return None

    created_at = int(datetime.now().timestamp())
    conf_tag = f"conf_{confidence}"

    if len(suggestion) < 12 :
        return None

    return {
        "roulette_id": roulette["slug"],
        "roulette_name": roulette["name"],
        "roulette_url": roulette["url"],
        "pattern": "PUXADOS-STRIDE",
        "triggers": target,
        "targets": suggestion,
        "bets": suggestion,
        "passed_spins": 0,
        "spins_required": 0,
        "spins_count": 0,
        "gales": 10,
        "score": 0,
        "snapshot": numbers[:50],
        "status": "processing",
        "message": f"Base {target} | conf {confidence} | ocorrencias {base_count}",
        "tags": [conf_tag],
        "temp_state": {
            "confidence": confidence,
            "base_count": base_count,
            "window": WINDOW,
            "top_window": TOP_WINDOW,
            "top_plus1": TOP_PLUS1,
        },
        "created_at": created_at,
        "timestamp": created_at,
    }

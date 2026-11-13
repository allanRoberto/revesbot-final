"""Shared fixtures, including a real table observed on the production page."""
from __future__ import annotations

import random
from typing import Any

from contextual_ranking.rules import neighbors_of

# /analise-similaridade-contextual on 2026-11-13 12:07 (no live results yet,
# nothing clicked). Rows are listed in the order the page displayed them.
PRODUCTION_CURRENT_CONTEXT = [1, 16, 0, 15, 34]
PRODUCTION_SEQUENCE = [23, 12, 32, 7]
PRODUCTION_ROWS = [
    ([15, 17, 24, 15, 9], [23, 35, 32, 7], [30, 16, 6, 18, 10], (1, 2, 52)),
    ([34, 13, 18, 0, 10], [23, 28, 0, 7], [16, 28, 34, 0, 8], (2, 0, 40)),
    ([19, 17, 25, 0, 22], [32, 21, 0, 7], [35, 6, 28, 23, 27], (1, 2, 52)),
    ([24, 16, 23, 25, 18], [32, 12, 15, 29], [17, 27, 20, 14, 2], (1, 0, 20)),
    ([9, 14, 11, 5, 34], [10, 35, 23, 7], [10, 19, 0, 26, 22], (1, 0, 20)),
    ([20, 29, 15, 7, 23], [10, 35, 23, 28], [18, 1, 1, 27, 21], (1, 1, 36)),
    ([25, 21, 15, 17, 26], [23, 28, 15, 28], [20, 2, 11, 8, 25], (1, 2, 52)),
    ([33, 10, 32, 18, 0], [23, 35, 23, 29], [29, 2, 36, 24, 16], (1, 2, 52)),
    ([23, 32, 13, 15, 15], [23, 21, 23, 29], [17, 27, 1, 35, 1], (1, 1, 36)),
    ([4, 10, 20, 10, 24], [23, 12, 32, 28], [2, 14, 29, 0, 22], (0, 2, 32)),
    ([4, 23, 35, 19, 31], [10, 12, 32, 7], [27, 11, 32, 3, 35], (0, 1, 16)),
    ([4, 13, 25, 27, 19], [23, 12, 15, 7], [10, 29, 22, 31, 12], (0, 1, 16)),
    ([25, 2, 36, 20, 32], [23, 12, 0, 29], [29, 22, 10, 18, 17], (0, 2, 32)),
    ([31, 27, 32, 8, 17], [10, 12, 32, 28], [15, 33, 27, 2, 21], (0, 2, 32)),
    ([26, 35, 19, 25, 13], [10, 35, 23, 7], [31, 33, 16, 4, 27], (0, 2, 32)),
    ([17, 3, 13, 8, 12], [10, 12, 15, 7], [16, 11, 27, 16, 23], (0, 1, 16)),
    ([31, 23, 21, 33, 8], [10, 12, 0, 7], [16, 2, 19, 15, 25], (0, 1, 16)),
    ([11, 31, 14, 2, 20], [10, 12, 32, 29], [8, 31, 23, 23, 24], (0, 1, 16)),
    ([2, 10, 8, 6, 3], [23, 35, 32, 29], [2, 31, 28, 17, 4], (0, 1, 16)),
    ([6, 12, 14, 5, 35], [8, 35, 23, 7], [11, 1, 23, 1, 26], (0, 1, 16)),
    ([17, 6, 33, 8, 7], [23, 35, 15, 29], [1, 31, 6, 20, 17], (0, 2, 32)),
    ([23, 19, 15, 8, 6], [10, 21, 15, 29], [5, 13, 4, 12, 30], (1, 1, 36)),
    ([3, 30, 36, 28, 20], [23, 28, 15, 29], [18, 21, 12, 6, 3], (0, 1, 16)),
    ([2, 28, 35, 9, 19], [10, 12, 15, 29], [30, 36, 17, 29, 31], (0, 1, 16)),
    ([21, 5, 4, 19, 12], [10, 12, 0, 29], [28, 3, 30, 19, 29], (0, 1, 16)),
    ([20, 25, 29, 23, 19], [32, 21, 15, 28], [31, 2, 25, 5, 22], (0, 2, 32)),
    ([0, 10, 26, 29, 18], [10, 21, 0, 29], [32, 15, 24, 19, 14], (1, 0, 20)),
    ([12, 13, 35, 28, 8], [32, 28, 0, 29], [33, 2, 27, 25, 6], (0, 0, 0)),
    ([6, 4, 3, 8, 28], [8, 21, 15, 28], [34, 33, 10, 30, 26], (0, 1, 16)),
    ([7, 22, 30, 7, 4], [10, 28, 15, 29], [29, 27, 24, 25, 6], (0, 0, 0)),
]


def production_occurrences() -> list[dict[str, Any]]:
    return [
        {"id": f"prod-{index + 1}", "preceding": list(preceding), "preceding_complete": True,
         "preceding_lookup_status": "complete", "context": list(context), "following": list(following)}
        for index, (preceding, context, following, _) in enumerate(PRODUCTION_ROWS)
    ]


def _related(rng: random.Random, anchors: list[int], chance: float) -> int:
    if anchors and rng.random() < chance:
        anchor = rng.choice(anchors)
        return anchor if rng.random() < 0.5 else rng.choice(neighbors_of(anchor))
    return rng.randrange(37)


def random_case(rng: random.Random) -> dict[str, Any]:
    current = [rng.randrange(37) for _ in range(5)]
    sequence = [rng.randrange(37) for _ in range(4)]
    occurrences = []
    for index in range(rng.choice((0, 1, 3, 4, 8, 20, 45, 100))):
        complete = rng.random() > 0.12
        occurrence = {
            "id": f"occ-{index}",
            "context": [_related(rng, sequence, 0.75) for _ in range(4)],
            "following": [rng.randrange(37) for _ in range(5)],
            "preceding_complete": complete,
            "preceding_lookup_status": "complete" if complete else rng.choice(("missing", "after_cutoff")),
        }
        if complete:
            occurrence["preceding"] = [_related(rng, current, 0.45) for _ in range(5)]
        if rng.random() < 0.03:
            occurrence["following"] = occurrence["following"][:4]
        occurrences.append(occurrence)
    if occurrences and rng.random() < 0.25:
        # Many identical rows force the final index tie-break.
        clone = dict(occurrences[0])
        occurrences.extend({**clone, "id": f"clone-{n}"} for n in range(rng.randint(2, 6)))
    pool = [n for row in occurrences for n in row["following"] + row["context"]] or list(range(37))
    live = sorted({rng.choice(pool) for _ in range(rng.randint(0, 4))})
    selected = sorted({rng.randrange(37) for _ in range(rng.randint(0, 3))}) if rng.random() < 0.2 else []
    return {"current_context": current, "sequence": sequence, "live": live,
            "selected": selected, "occurrences": occurrences}

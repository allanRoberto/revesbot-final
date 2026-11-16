"""A scripted stand-in for the ranking engine: every result gets the next scripted top 7."""
from __future__ import annotations

from typing import Any, Sequence

from contextual_ranking import STRATEGY_VERSION
from contextual_ranking.engine import ROULETTE_ID, SPIN_MEMORY, iso

# Rankings (top 7) used by the tests, and the bet each one produces.
PAIR_37 = [3, 7, 20, 25, 28, 12, 31]  # pair 3-7
PROTECTION_37 = [2, 12, 21, 25, 28]  # triples 21-2-25 and 7-28-12: between the group of 3 and the group of 7
# intersection + neighbors + the two numbers of the pair + protection numbers
BET_37 = [1, 2, 3, 6, 7, 12, 13, 16, 21, 24, 25, 27, 28, 33, 36]
PAIR_39 = [9, 3, 22, 18, 29, 12, 35]  # pair 3-9
IGNORED_PAIR = [6, 9, 20, 25, 28, 12, 31]  # pair 6-9 is an exception: it never opens a signal
NO_PAIR = [3, 20, 25, 28, 12, 31, 35]  # a single number from 0 to 9
TOO_MANY = [1, 2, 3, 20, 25, 28, 12]  # three numbers from 0 to 9
NO_INTERSECTION = [0, 7, 20, 25, 28, 12, 31]  # pair 0-7 has no bet


class ScriptedRanking:
    def __init__(self, tops: Sequence[Sequence[int]]):
        self.tops = [list(top) for top in tops]
        self.taken = 0

    def _take(self) -> list[int]:
        top = self.tops[min(self.taken, len(self.tops) - 1)]
        self.taken += 1
        return top

    @staticmethod
    def _ranking(top: Sequence[int], trigger: dict[str, Any]) -> dict[str, Any]:
        return {
            "top": [{"position": index + 1, "number": number, "points": 10, "exact": 1, "neighbor": 0}
                    for index, number in enumerate(top)],
            "full": [[number, 10, 1, 0] for number in top], "analyzed_results": 280, "maximum": 2800,
            "sources": [], "built_after": trigger,
        }

    def _state(self, base: dict[str, Any], spins: list[dict[str, Any]], recent: list[dict[str, Any]],
               now) -> dict[str, Any]:
        return {
            **base, "strategy_version": STRATEGY_VERSION, "roulette_id": ROULETTE_ID,
            "spins": spins, "searches": [], "analysis": [], "recent_results": recent[-3:], "open_signals": [],
            "ranking": self._ranking(self._take(), spins[-1]),
            "last_processed": {"history_id": spins[-1]["history_id"], "timestamp": spins[-1]["timestamp"]},
            "version": int(base.get("version") or 0) + 1, "updated_at": iso(now),
        }

    def process(self, state, result, search, now):
        on_screen = [row["number"] for row in (state.get("ranking") or {}).get("top") or []]
        spins = (list(state.get("spins") or []) + [result])[-SPIN_MEMORY:]
        recent = list(state.get("recent_results") or []) + [
            {**result, "hit": (result["number"] in on_screen) if on_screen else None},
        ]
        return self._state(state, spins, recent, now), []

    def rebuild(self, previous, spins, search, now):
        spins = list(spins)[-SPIN_MEMORY:]
        recent = [{**item, "hit": None} for item in spins[-3:]]
        return self._state({"version": int((previous or {}).get("version") or 0)}, spins, recent, now)

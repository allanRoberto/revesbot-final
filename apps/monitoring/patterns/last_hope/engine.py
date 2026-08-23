from __future__ import annotations

from collections import Counter
from typing import Sequence

from apps.monitoring.patterns.core.contracts import (
    PatternCandidate,
    PatternEngine,
    Spin,
)


WHEEL_ORDER = [
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23,
    10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26,
]
WHEEL_INDEX = {number: index for index, number in enumerate(WHEEL_ORDER)}
EXACT_MIRRORS = {
    2: 20, 3: 30, 6: 9, 9: 6, 12: 21, 13: 31, 16: 19, 19: 16,
    20: 2, 21: 12, 23: 32, 26: 29, 29: 26, 30: 3, 31: 13, 32: 23,
}
LIB_STRINGS = {
    "QQ", "QQQ", "QQQQ", "QF", "QFQ", "QFFQ", "FQ", "FQQ", "FQFQ",
    "QNQ", "QNF", "FNQ", "QNFQ", "QQFQ", "QFQQ", "FQQQ", "QQQF",
    "NQQ", "QQN", "QFN", "NFQ", "FQN", "NQF", "QNQN", "QNQNQ",
    "QNNQNNQ", "QNNQ", "QQNQ", "QQNNQ", "NNQNNQNNQ", "NNQNQQNQ",
    "QQNQQ", "NNNQ", "QNNN", "QNNNQNNNQ",
}


class DynamicBehaviorAnalyzer:
    def __init__(
        self,
        hot_numbers: list[int],
        cold_numbers: list[int],
        max_memory: int = 30,
        min_score_watch: float = 0.75,
    ):
        self.hot_numbers = set(hot_numbers)
        self.cold_numbers = set(cold_numbers)
        self.max_memory = max_memory
        self.min_score_watch = min_score_watch

    def classify(self, number: int) -> str:
        if number in self.hot_numbers:
            return "Q"
        if number in self.cold_numbers:
            return "F"
        return "N"

    @staticmethod
    def wheel_neighbors(number: int, radius: int = 1) -> set[int]:
        if number not in WHEEL_INDEX:
            return set()
        index = WHEEL_INDEX[number]
        result: set[int] = set()
        for offset in range(1, radius + 1):
            result.add(WHEEL_ORDER[(index - offset) % len(WHEEL_ORDER)])
            result.add(WHEEL_ORDER[(index + offset) % len(WHEEL_ORDER)])
        return result

    def similarity(self, first: int, second: int) -> float:
        if first == second:
            return 1.0
        if abs(first - second) == 1:
            return 0.75
        if first % 10 == second % 10:
            return 0.60
        if second in self.wheel_neighbors(first, 1):
            return 0.50
        if second == EXACT_MIRRORS.get(first, -1):
            return 0.45
        return 0.0

    def hot_ranking(
        self,
        current_block: list[int],
        past_block: list[int],
        target_number: int,
        hot_numbers: list[int],
    ) -> list[dict]:
        scores: list[dict] = []
        reference_numbers = set(past_block)
        for hot in hot_numbers:
            score = 0.20
            reason = "estrutural_generico"
            if hot == target_number:
                score, reason = 1.0, "alvo_exato_historico"
            elif EXACT_MIRRORS.get(hot, -1) == target_number:
                score, reason = 0.80, "espelho_alvo_historico"
            elif hot in reference_numbers:
                score, reason = 0.60, "quente_reaproveitado"
            elif any(
                hot in self.wheel_neighbors(reference, 1)
                or hot % 10 == reference % 10
                for reference in reference_numbers
            ):
                score, reason = 0.40, "vizinho_ou_terminal"
            scores.append({"hot": hot, "score": score, "reason": reason})
        return sorted(scores, key=lambda item: item["score"], reverse=True)

    def analyze(self, raw: list[int], trigger_offset: int = 4) -> dict | None:
        if len(raw) < 40:
            return None
        best_score = 0.0
        best_signal = None
        for index in range(
            trigger_offset + 1,
            min(len(raw) - 10, self.max_memory),
        ):
            target_number = raw[index - 1]
            if self.classify(target_number) != "Q":
                continue
            for past_length in range(2, 9):
                past_raw = raw[index : index + past_length]
                past_chrono = [self.classify(number) for number in reversed(past_raw)]
                past_string = "".join(past_chrono)
                full_past_string = past_string + "Q"
                for current_length in range(
                    max(2, past_length - 2),
                    min(9, past_length + 3),
                ):
                    current_raw = raw[
                        trigger_offset : trigger_offset + current_length
                    ]
                    current_chrono = [
                        self.classify(number) for number in reversed(current_raw)
                    ]
                    current_string = "".join(current_chrono)
                    is_variation = (
                        current_string.replace("N", "")
                        == past_string.replace("N", "")
                        and abs(len(current_string) - len(past_string)) <= 2
                    )
                    if not is_variation:
                        continue
                    is_library = full_past_string in LIB_STRINGS
                    minimum_length = min(current_length, past_length)
                    direct_similarity = sum(
                        self.similarity(current_raw[cursor], past_raw[cursor])
                        for cursor in range(minimum_length)
                    ) / float(minimum_length)
                    class_similarity = sum(
                        1
                        for cursor in range(minimum_length)
                        if self.classify(current_raw[cursor])
                        == self.classify(past_raw[cursor])
                    ) / float(minimum_length)
                    current_hots = {
                        number for number in current_raw if number in self.hot_numbers
                    }
                    past_hots = {
                        number for number in past_raw if number in self.hot_numbers
                    }
                    hot_overlap = (
                        len(current_hots.intersection(past_hots))
                        / float(max(len(current_hots), 1))
                        if current_hots
                        else 0.0
                    )
                    distance_score = max(
                        0.0,
                        1.0 - ((index - trigger_offset) / float(self.max_memory)),
                    )
                    score = (
                        0.35 * direct_similarity
                        + 0.25 * class_similarity
                        + 0.15 * hot_overlap
                        + 0.15 * distance_score
                    )
                    if is_library:
                        score += 0.10
                    if score <= best_score:
                        continue
                    ranking = self.hot_ranking(
                        current_raw,
                        past_raw,
                        target_number,
                        list(self.hot_numbers),
                    )
                    best_score = score
                    best_signal = {
                        "score": score,
                        "library_pattern": full_past_string if is_library else None,
                        "pattern_string": current_string + "Q",
                        "priority_hot": ranking[0]["hot"],
                        "target_paid": target_number,
                        "hot_ranking": ranking,
                        "trigger_number": current_raw[0],
                        "reference_block": list(reversed(past_raw)),
                        "current_block": list(reversed(current_raw)),
                        "direct_similarity": direct_similarity,
                        "class_similarity": class_similarity,
                        "hot_overlap": hot_overlap,
                    }
        return best_signal if best_score >= self.min_score_watch else None


class LastHopePattern(PatternEngine):
    def analyze(
        self,
        history: Sequence[Spin],
        *,
        roulette_id: str,
        payout: int,
    ) -> PatternCandidate | None:
        raw = [spin.value for spin in history]
        if len(raw) < 50:
            return None

        best_signal = None
        best_score = 0.0
        best_timeframe = None
        best_hot_numbers = None
        best_cold_numbers = None
        for timeframe in (50, 100, 200, 300, 500):
            counts = Counter(raw[: min(len(raw), timeframe)])
            frequency = sorted(counts.keys(), key=lambda number: counts[number], reverse=True)
            if len(frequency) < 8:
                continue
            hot_numbers = frequency[:4]
            cold_numbers = frequency[-4:]
            signal = DynamicBehaviorAnalyzer(
                hot_numbers=hot_numbers,
                cold_numbers=cold_numbers,
                max_memory=30,
            ).analyze(raw, trigger_offset=4)
            if signal and signal["score"] > best_score:
                best_score = signal["score"]
                best_signal = signal
                best_timeframe = timeframe
                best_hot_numbers = hot_numbers
                best_cold_numbers = cold_numbers

        if not best_signal or not best_hot_numbers or not best_cold_numbers:
            return None
        bet_numbers = set(best_hot_numbers)
        bet_numbers.add(0)
        if 0 in best_hot_numbers:
            bet_numbers.update({10, 5, 23})
        if any(number in bet_numbers for number in raw[:4]):
            return None

        details = {
            **best_signal,
            "timeframe": best_timeframe,
            "hot_numbers": best_hot_numbers,
            "cold_numbers": best_cold_numbers,
        }
        return PatternCandidate(
            trigger_number=int(best_signal["trigger_number"]),
            bet_numbers=tuple(sorted(bet_numbers)),
            target_name=f"Alvo {best_signal['priority_hot']}",
            details=details,
        )

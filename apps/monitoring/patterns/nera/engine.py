from __future__ import annotations

from typing import Any, Mapping, Sequence

from apps.monitoring.patterns.core.contracts import (
    AttemptGate,
    PatternCandidate,
    PatternEngine,
    Spin,
)


WHEEL_ORDER = [
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23,
    10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26,
]
MIRRORS = {
    1: 10, 10: 1, 2: 20, 20: 2, 3: 30, 30: 3, 6: 9, 9: 6,
    12: 21, 21: 12, 13: 31, 31: 13, 16: 19, 19: 16,
    23: 32, 32: 23, 26: 29, 29: 26,
}
NERA_NUMBERS = {6, 9, 12, 21, 13, 31, 16, 19, 23, 32, 26, 29}
NERA_TARGET_MIRRORS = {
    1: [10, 11], 2: [20, 22], 3: [30, 33], 6: [9], 9: [6],
    10: [1, 10], 11: [10, 1], 12: [21], 13: [31], 14: [34],
    15: [5], 16: [19], 17: [27], 18: [28], 19: [16],
    20: [2, 22], 21: [12], 22: [2, 20], 23: [32], 26: [29],
    27: [17], 28: [18], 29: [26], 30: [3, 30], 31: [13],
    32: [23], 33: [3, 30], 34: [14],
}


def wheel_neighbors(number: int, count: int = 1) -> set[int]:
    if number not in WHEEL_ORDER:
        return set()
    index = WHEEL_ORDER.index(number)
    result: set[int] = set()
    for offset in range(1, count + 1):
        result.add(WHEEL_ORDER[(index - offset) % len(WHEEL_ORDER)])
        result.add(WHEEL_ORDER[(index + offset) % len(WHEEL_ORDER)])
    return result


class NeraPattern(PatternEngine):
    @staticmethod
    def _fall_is_valid(index: int, raw: list[int], trigger: int, mirror: int) -> bool:
        for cursor in range(max(0, index - 3), min(len(raw), index + 4)):
            if cursor == index:
                continue
            if raw[cursor] in {0, trigger, mirror}:
                return False
        return True

    @staticmethod
    def _nexus(number: int) -> set[int]:
        result = {number, MIRRORS.get(number, number)}
        neighbors = wheel_neighbors(number, 1)
        result.update(neighbors)
        result.update(MIRRORS.get(value, value) for value in neighbors)
        return result

    def analyze(
        self,
        history: Sequence[Spin],
        *,
        roulette_id: str,
        payout: int,
    ) -> PatternCandidate | None:
        raw = [spin.value for spin in history]
        if len(raw) < 20 or raw[0] not in NERA_NUMBERS:
            return None

        trigger = raw[0]
        trigger_mirror = MIRRORS.get(trigger, trigger)
        valid_falls: list[int] = []
        for index in range(1, min(100, len(raw))):
            if raw[index] == trigger and self._fall_is_valid(
                index, raw, trigger, trigger_mirror
            ):
                valid_falls.append(index)
                if len(valid_falls) == 3:
                    break
        if len(valid_falls) < 3:
            return None

        windows = [
            raw[max(0, index - 3) : min(len(raw), index + 4)]
            for index in valid_falls
        ]
        candidates: list[dict[str, int]] = []
        for number in range(1, 37):
            if number in {trigger, trigger_mirror}:
                continue
            nexus = self._nexus(number)
            if all(any(value in nexus for value in window) for window in windows):
                strength = sum(
                    1 for window in windows for value in window if value in nexus
                )
                candidates.append({"number": number, "strength": strength})
        if not candidates:
            return None
        candidates.sort(key=lambda item: item["strength"], reverse=True)
        target = candidates[0]["number"]

        target_mirrors = set(
            NERA_TARGET_MIRRORS.get(target, [MIRRORS.get(target, target)])
        )
        base_bet = {target} | target_mirrors | wheel_neighbors(target, 1)
        hidden_mirrors: set[int] = set()
        for neighbor in wheel_neighbors(target, 1):
            if neighbor in NERA_TARGET_MIRRORS:
                hidden_mirrors.update(NERA_TARGET_MIRRORS[neighbor])
            else:
                hidden_mirrors.add(MIRRORS.get(neighbor, neighbor))

        inversion_set = base_bet | hidden_mirrors | {trigger, trigger_mirror}
        if any(
            value in inversion_set and value not in {trigger, trigger_mirror}
            for value in raw[1:4]
        ):
            return None

        bet_numbers = tuple(
            sorted(base_bet | hidden_mirrors | {trigger, trigger_mirror, 0})
        )
        delay = 0
        for index in range(1, 4):
            if index + 1 >= len(raw):
                continue
            first, second = raw[index], raw[index + 1]
            if abs(first - second) <= 3 or first % 10 == second % 10 or first == second:
                delay = 2
                break

        return PatternCandidate(
            trigger_number=trigger,
            bet_numbers=bet_numbers,
            target_name=f"Alvo {target}",
            runtime={
                "delay_remaining": delay,
                "delay_triggered": delay > 0,
                "last_observed_number": trigger,
            },
            details={
                "target": target,
                "target_strength": candidates[0]["strength"],
                "trigger_mirror": trigger_mirror,
                "valid_falls": valid_falls,
                "influence_windows": windows,
            },
        )

    def before_attempt(self, signal: Mapping[str, Any], spin: Spin) -> AttemptGate:
        runtime = dict(signal.get("runtime") or {})
        if signal.get("attempts"):
            return AttemptGate(count_attempt=True, runtime=runtime)

        previous = int(runtime.get("last_observed_number", signal.get("trigger_number", 0)))
        delay_remaining = int(runtime.get("delay_remaining") or 0)
        intercepted = (
            abs(spin.value - previous) <= 3
            or spin.value % 10 == previous % 10
            or spin.value == previous
        )
        runtime["last_observed_number"] = spin.value
        if intercepted:
            runtime["delay_remaining"] = 2
            runtime["delay_triggered"] = True
            return AttemptGate(False, runtime, "nera_delay_intercepted")
        if delay_remaining > 0:
            runtime["delay_remaining"] = delay_remaining - 1
            return AttemptGate(False, runtime, "nera_delay_countdown")
        return AttemptGate(True, runtime)

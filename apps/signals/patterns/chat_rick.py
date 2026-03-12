from collections import Counter
from typing import List, Dict


class RouletteAnalyzer:
    def __init__(self, numbers: List[int]):
        self.numbers = numbers
        self.total_spins = len(numbers)
        self.frequency = Counter(numbers)

    def frequency_percentage(self) -> Dict[int, float]:
        return {
            n: (count / self.total_spins) * 100
            for n, count in self.frequency.items()
        }

    def expected_average(self) -> float:
        return self.total_spins / 37

    def detect_triggers(self) -> List[int]:
        avg = self.expected_average()
        triggers = []

        for number, count in self.frequency.items():
            if count > avg * 1.15:
                triggers.append(number)

        return sorted(triggers)

    def detect_entries(self, triggers: List[int], window: int = 3) -> List[int]:
        post_trigger_hits = Counter()

        for i, num in enumerate(self.numbers):
            if num in triggers:
                for j in range(1, window + 1):
                    if i + j < self.total_spins:
                        post_trigger_hits[self.numbers[i + j]] += 1

        if not post_trigger_hits:
            return []

        avg_hits = sum(post_trigger_hits.values()) / len(post_trigger_hits)

        entries = [
            n for n, c in post_trigger_hits.items()
            if c >= avg_hits
        ]

        return sorted(entries)

    def generate_strategy(self):
        triggers = self.detect_triggers()
        entries = self.detect_entries(triggers)

        reduced_entries = []
        for number in entries[:4] + triggers[:4]:
            if number not in reduced_entries:
                reduced_entries.append(number)

        if len(reduced_entries) < 8:
            for number, _count in self.frequency.most_common():
                if number not in reduced_entries:
                    reduced_entries.append(number)
                    if len(reduced_entries) >= 8:
                        break

        if len(reduced_entries) < 8:
            for number in range(37):
                if number not in reduced_entries:
                    reduced_entries.append(number)
                    if len(reduced_entries) >= 8:
                        break

        full_entries = []
        for number in entries[:6] + triggers[:6]:
            if number not in full_entries:
                full_entries.append(number)

        if len(full_entries) < 12:
            for number, _count in self.frequency.most_common():
                if number not in full_entries:
                    full_entries.append(number)
                    if len(full_entries) >= 12:
                        break

        if len(full_entries) < 12:
            for number in range(37):
                if number not in full_entries:
                    full_entries.append(number)
                    if len(full_entries) >= 12:
                        break

        return {
            "gatilhos_X": triggers,
            "entrada_cheia_Y_12": full_entries,
            "entrada_reduzida_Y_8": reduced_entries
        }

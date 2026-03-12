from collections import defaultdict, Counter
from typing import List, Dict, Tuple
from helpers.utils.get_neighbords import get_neighbords


# ---------------------------------------------------------------------------

class HotColdTracker:
    def __init__(self) -> None:
        self.counts: Counter[int] = Counter()
        self.total_spins: int = 0

    def add_spin(self, number: int) -> None:
        """Registra uma nova jogada."""
        self.counts[number] += 1
        self.total_spins += 1

    def bulk_add(self, spins: List[int]) -> None:
        """Processa uma lista de números de uma vez."""
        for n in spins:
            if n not in(2, 4, 5, 6, 7, 9, 13, 16, 17, 19, 21, 34, 27, 22, 25,28, 29, 33):
                continue
            else :
                self.add_spin(n)

    # --- Consultas ----------------------------------------------------------

    def top_n(self, n: int = 5) -> List[Tuple[int, int]]:
        """Retorna os n números mais quentes [(numero, ocorrências), …]."""
        return self.counts.most_common(n)

    def bottom_n(self, n: int = 5) -> List[Tuple[int, int]]:
        """Retorna os n números mais frios."""
        return self.counts.most_common()[:-n-1:-1]

    def hot_number(self) -> Tuple[int, int]:
        """Número mais quente (num, ocorrências)."""
        if not self.counts:
            raise ValueError("Ainda não há jogadas registradas")
        return self.counts.most_common(1)[0]

    def region(self, number: int) -> List[int]:
        """Vizinhos diretos do número na roleta europeia."""
        return get_neighbords(number)

    def summary(self) -> None:
        """Imprime um resumo rápido no console."""
        hot, freq = self.hot_number()
        print(f"Total de jogadas: {self.total_spins}")
        print(f"Número quente: {hot} ({freq}x) — Vizinhos: {self.region(hot)}")
        cold_list = self.bottom_n(3)
        print("Top 5 quentes:", self.top_n(5))
        print("Top 5 frios  :", self.bottom_n(5))
        print("3 mais frios :", cold_list)



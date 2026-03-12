# dominance_filter.py
from collections import Counter
from typing import Dict, List, Tuple, Sequence

# ----- 1) Vizinhos na roleta (1 para cada lado)
WHEEL_NEIGHBORS: Dict[int, Tuple[int, int]] = {
    0: (26, 32), 1: (33, 20), 2: (21, 25), 3: (26, 35), 4: (19, 21),
    5: (24, 10), 6: (27, 34), 7: (28, 29), 8: (12, 30), 9: (31, 22),
    10: (23, 5), 11: (36, 13), 12: (8, 3), 13: (11, 27), 14: (20, 31),
    15: (32, 19), 16: (33, 24), 17: (34, 25), 18: (29, 22), 19: (15, 4),
    20: (14, 1), 21: (4, 2), 22: (9, 18), 23: (10, 30), 24: (5, 16),
    25: (2, 17), 26: (3, 0), 27: (13, 6), 28: (7, 12), 29: (18, 7),
    30: (8, 23), 31: (14, 9), 32: (0, 15), 33: (1, 16), 34: (6, 17),
    35: (3, 26), 36: (13, 11),
}


def get_neighbors(n: int) -> List[int]:
    """Retorna o par de vizinhos (esq, dir) de um número na roleta europeia."""
    return list(WHEEL_NEIGHBORS.get(n, []))


# ----- 2) Cálculo de dominância
def compute_dominance(
    next_numbers: Sequence[int],           # os 3 números logo após o gatilho
    neighbor_fn=get_neighbors
) -> Tuple[int, float]:
    """
    Retorna (terminal_dominante, fração_dominante).

    Exemplo: se os vizinhos forem [1,20,33,14,31,20] → terminais 1,0,3,4,1,0
    terminal 0 aparece 2/6 = 0.333, terminal 1 = 0.333, terminal 3 = 0.167 …
    Dominante = 0 (ou 1); fração = 0.333.
    """
    neighbors = []
    for num in next_numbers:
        neighbors.extend(neighbor_fn(num))

    term_freq = Counter(n % 10 for n in neighbors)
    top_term, top_count = term_freq.most_common(1)[0]
    dominance = top_count / sum(term_freq.values())
    return top_term, dominance


# ----- 3) Filtro pronto para usar
RISKY_TRIGGERS = {33, 28, 13, 17, 4, 5, 3, 20, 10, 7}


def should_bet(
    trigger: int,
    next_numbers: Sequence[int],
    dominance_cut: float = 0.60
) -> bool:
    """
    True  -> pode apostar
    False -> cancelar (dominância fraca ou gatilho de risco)
    """
    term, dom = compute_dominance(next_numbers)

    # Se gatilho é de risco, exige dominância maior
    if trigger in RISKY_TRIGGERS:
        dominance_cut += 0.05          # ex.: 0.60 → 0.65

    return dom >= dominance_cut

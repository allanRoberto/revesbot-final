from typing import List, Dict, Any, Optional
from helpers.utils.filters import first_index_after, soma_digitos, get_numbers_by_terminal
from helpers.utils.get_figure import get_figure

# === Configurações de roleta ===
ROULETTE_WHEEL = [
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36,
    11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9,
    22, 18, 29, 7, 28, 12, 35, 3, 26
]

MIRRORS_MAP = {
    1: [10], 10: [1],
    2: [20], 20: [2],
    3: [30], 30: [3],
    6: [9],  9: [6],
    11: [22, 33], 22: [11, 33], 33: [11, 22],
    12: [21], 21: [12],
    13: [31], 31: [13],
    16: [19], 19: [16],
    23: [32], 32: [23],
    26: [29], 29: [26],
}

def get_neighbors(number: int, radius: int = 2) -> List[int]:
    if number not in ROULETTE_WHEEL:
        return []

    idx = ROULETTE_WHEEL.index(number)
    n = len(ROULETTE_WHEEL)
    neighbors = []

    for offset in range(-radius, radius + 1):
        if offset == 0:
            continue
        neighbors.append(ROULETTE_WHEEL[(idx + offset) % n])

    return neighbors

def get_mirrors(number: int) -> List[int]:
    return MIRRORS_MAP.get(number, [])

def get_terminal(number: int) -> int:
    return abs(number) % 10

def digit_sum(number: int) -> int:
    return sum(int(d) for d in str(abs(number)))


DEFAULT_RELATION_WEIGHTS: Dict[str, float] = {
    "igual": 5.0,         # mais forte
    "espelho": 4.0,
    "vizinho": 3.0,
    "terminal": 2.0,
    "soma_digitos": 1.0,
}


def find_relations_between_lists(
    list1: List[int],
    list2: List[int],
    relation_weights: Optional[Dict[str, float]] = None

) -> List[Dict[str, Any]]:
    """
    Verifica relações entre números de duas listas com pesos.

    Relações consideradas:
    - igual
    - espelho
    - vizinho (raio 2 na roda)
    - mesmo terminal
    - mesma soma de dígitos

    Retorna uma lista de dicts com:
    {
        "a": <número da lista1>,
        "b": <número da lista2>,
        "relations": ["igual", "espelho", ...],
        "score": <soma dos pesos das relações>
    }
    """
    weights = {**DEFAULT_RELATION_WEIGHTS, **(relation_weights or {})}
    relations = []

    for a in list1:
        mirrors_a = set(get_mirrors(a))
        neighbors_a = set(get_neighbors(a, radius=2))
        terminal_a = get_terminal(a)
        sum_a = digit_sum(a)

        for b in list2:
            rel_types = []

            # 1) Números iguais
            if a == b:
                rel_types.append("igual")

            # 2) Espelhos
            if b in mirrors_a:
                rel_types.append("espelho")

            # 3) Vizinhos
            if b in neighbors_a:
                rel_types.append("vizinho")

            # 4) Mesmo terminal
            if terminal_a == get_terminal(b):
                rel_types.append("terminal")

            # 5) Mesma soma de dígitos
            if sum_a == digit_sum(b):
                rel_types.append("soma_digitos")

            if rel_types:
                score = sum(weights[r] for r in rel_types)
                relations.append({
                    "a": a,
                    "b": b,
                    "relations": rel_types,
                    "score": score,
                })

    return relations


def has_any_relation(list1: List[int], list2: List[int]) -> bool:
    return bool(find_relations_between_lists(list1, list2))



def process_roulette(roulette, numbers) :

    alvo = numbers[0]


    check1 = first_index_after(numbers, alvo, start=1)

    if not check1  == None :
        before_check_1 = numbers[check1 - 1]
        after_check_1  = numbers[check1 + 1]

    l1 = [numbers[1]]
    l2 = [before_check_1, numbers[check1 - 2]]

    rels = find_relations_between_lists(l1, l2)
    bet = []

    if len(rels) :
        print ("Não encontrou relação", roulette["name"])
    for r in rels:
        print(r)


        neighbords = get_neighbors(numbers[after_check_1], 1)
        mirror = get_mirrors(numbers[after_check_1])
        terminals = get_numbers_by_terminal(get_terminal(numbers[after_check_1]))
        figures  = get_figure(soma_digitos(numbers[after_check_1]))


        bet.extend([
            numbers[after_check_1] - 1,
            numbers[after_check_1],
            numbers[after_check_1] + 1,
            *neighbords,
            *mirror,
            *terminals,
            *figures,
        ])

        bet = sorted(set(bet));

        return {
            "roulette_id": roulette['slug'],
            "roulette_name" : roulette["name"],
            "roulette_url" : roulette["url"],
            "pattern" : "ESTELAR",
            "triggers":[numbers[0]],
            "targets":[*bet],
            "bets": bet,
            "passed_spins" : 0,
            "spins_required" : 2,
            "spins_count": 0,
            "gales" : 10,
            "score" : 0,
            "snapshot":numbers[:300],
            "status":"processing",
            "message" : "Gatilho encontrado!",
            "tags" : [],
        }


       
from typing import List, Tuple, Dict
from collections import defaultdict, namedtuple

# ----------------------------
# Configurações da roda (europeia / single zero)
# ----------------------------
WHEEL = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36,
         11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9,
         22, 18, 29, 7, 28, 12, 35, 3, 26]

IDX = {n: i for i, n in enumerate(WHEEL)}

def neighbors1(n: int) -> set:
    """Retorna o conjunto com os dois vizinhos imediatos de n na roda."""
    i = IDX[n]
    left = WHEEL[(i - 1) % len(WHEEL)]
    right = WHEEL[(i + 1) % len(WHEEL)]
    return {left, right}

def terminal_group(n: int) -> set:
    """
    Retorna o conjunto de 'terminais' para n (mesmo dígito final).
    Ex.: n=9 -> {19,29}; n=0 -> {10,20,30}; n=10 -> {0,20,30}, etc.
    (Não inclui o próprio n.)
    """
    d = n % 10
    group = {x for x in range(37) if x % 10 == d and x != n}
    # Garantir 0/10/20/30 como um grupo coerente:
    if d == 0:
        group.update({0, 10, 20, 30})
        group.discard(n)
    return group

def match_position(base_val: int, obs_val: int) -> Tuple[str, bool]:
    """
    Classifica a correspondência de uma posição.
    Retorna (tipo, is_terminal):
        tipo ∈ {"exact", "neighbor", "terminal", "none"}
        is_terminal: True se usou terminal nessa posição.
    """
    if obs_val == base_val:
        return ("exact", False)
    if obs_val in neighbors1(base_val):
        return ("neighbor", False)
    if obs_val in terminal_group(base_val):
        return ("terminal", True)
    return ("none", False)

def match_triple(base: Tuple[int, int, int],
                 obs: Tuple[int, int, int]) -> Tuple[bool, int, int]:
    """
    Verifica se 'obs' casa com 'base' segundo as regras:
    - Cada posição deve ser exact/neighbor/terminal.
    - Pelo menos 1 exato no trio.
    - No máximo 1 terminal no trio.
    Retorna (ok, exact_count, terminal_count).
    """
    exact = 0
    term = 0
    for b, o in zip(base, obs):
        t, is_term = match_position(b, o)
        if t == "none":
            return (False, 0, 0)
        if t == "exact":
            exact += 1
        if is_term:
            term += 1
            if term > 1:
                return (False, 0, 0)
    if exact >= 1:
        return (True, exact, term)
    return (False, 0, 0)

Occurrence = namedtuple("Occurrence", ["index", "triple", "exact", "term"])

def process_roulette(roulette, history: List[int]) -> List[Tuple[int, int, int]]:
    """
    Implementa o pipeline completo:
    - Lê de baixo para cima.
    - Gera trios base.
    - Busca 2 ocorrências válidas por trio (após o trio base).
    - Resolve conflitos por critério (ocorrências, exatos, terminais, recência).
    - Retorna somente a lista dos trios base aprovados.
    """
    if not history:
        return []

    # 1) Ler de baixo para cima (mais antigo -> mais recente)
    seq = list(reversed(history[:200]))

    candidates: Dict[Tuple[int,int,int], dict] = {}

    n = len(seq)
    # 2) Gera trios base percorrendo o histórico
    for i in range(n - 2):
        base = (seq[i], seq[i+1], seq[i+2])

        # 3) Procurar duas ocorrências válidas após o trio base
        occs: List[Occurrence] = []
        for k in range(i + 1, n - 2):
            obs = (seq[k], seq[k+1], seq[k+2])
            ok, ex_ct, term_ct = match_triple(base, obs)
            if ok:
                occs.append(Occurrence(k, obs, ex_ct, term_ct))
                if len(occs) == 2:
                    break

        if len(occs) >= 2:
            # Guarda o melhor conjunto de ocorrências para esse base
            score = (
                len(occs),                               # 1) mais ocorrências
                sum(o.exact for o in occs),             # 2) mais exatos
                -sum(o.term for o in occs),             # 3) menos terminais
                max(o.index for o in occs)              # 4) mais recente (maior índice)
            )
            prev = candidates.get(base)
            if (prev is None) or (score > prev["score"]):
                candidates[base] = {"score": score, "occs": occs, "base_index": i}

    if not candidates:
        return []

    # 4) Resolver conflitos entre bases "similares"
    # Estratégia prática:
    # - Primeiro, agrupar por (a,b) (dois primeiros fixos) e manter a melhor.
    # - Depois, agrupar por (b,c) e manter a melhor.
    def reduce_by_key(key_func, items):
        buckets = defaultdict(list)
        for b, payload in items:
            buckets[key_func(b)].append((b, payload))
        chosen = {}
        for key, rows in buckets.items():
            # Escolhe por 'score' lexicográfico
            b_best, p_best = max(rows, key=lambda t: t[1]["score"])
            chosen[b_best] = p_best
        return list(chosen.items())

    items = list(candidates.items())
    # Agrupa por prefixo (a,b)
    items = reduce_by_key(lambda b: (b[0], b[1]), items)
    # Agrupa por sufixo (b,c)
    items = reduce_by_key(lambda b: (b[1], b[2]), items)

    # 5) Ordenar por critério final (mesma ordem usada para pontuação)
    items.sort(key=lambda t: t[1]["score"], reverse=True)

    # 6) Retornar somente os trios base
    bases_sorted = [b for b, _ in items]
    print("=" * 60)
    print(f"Roleta : {roulette['name']}")
    print(bases_sorted)
    print("=" * 60)
    return None

# ----------------------------
# Exemplo de uso:
# ----------------------------
if __name__ == "__main__":
    # Cole seu histórico como linhas (mais recente no topo).
    raw_text = """
    2
    16
    0
    17
    21
    31
    24
    15
    2
    19
    """
    # Parse
    history = [int(x.strip()) for x in raw_text.split() if x.strip().lstrip("-").isdigit()]

    result = process_roulette(history)
    # Saída: somente os trios base, um por linha
    for (a, b, c) in result:
        print(a, b, c)

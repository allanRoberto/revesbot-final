import re
from collections import Counter
from math import exp


# ======================
# CONFIGURAÇÕES
# ======================
TOP_N = 13          # troque para 9 se quiser
TOP_TRIGGERS = 5
HALF_LIFE = 35      # controla peso da recência
ZERO_FORCE = True   # sempre proteger o zero

# ======================
# GRUPOS FIXOS (FIÉIS AO MÉTODO)
# ======================
CAVALOS = [
    {1,4,7,11,14,17,21,24,27,31,34},        # 147
    {2,5,8,12,15,18,22,25,28,32,35},        # 258
    {3,6,9,13,16,19,23,26,29,33,36},        # 369
    {0,4,7,10,14,17,20,24,27,30,34},        # 047
]

TERMINAIS = {
    0:{0,10,20,30}, 1:{1,11,21,31}, 2:{2,12,22,32},
    3:{3,13,23,33}, 4:{4,14,24,34}, 5:{5,15,25,35},
    6:{6,16,26,36}, 7:{7,17,27},
    8:{8,18,28}, 9:{9,19,29}
}

DEZENA_20 = set(range(20,30))

# ======================
# FUNÇÕES
# ======================
def parse_numbers(text):
    nums = [int(n) for n in re.findall(r"\d+", text)]
    return [n for n in nums if 0 <= n <= 36]

def recency_weight(index):
    return exp(-index / HALF_LIFE)

def analyze(history_text):
    spins = history_text
    if not spins:
        return None

    scores = {n:0.0 for n in range(37)}

    # 1) PESO DE RECÊNCIA
    for i, n in enumerate(spins):
        scores[n] += recency_weight(i)

    # 2) REPETIÇÃO
    counts = Counter(spins[:40])
    for n, c in counts.items():
        if c > 1:
            scores[n] += 0.15 * (c - 1)

    # 3) TERMINAIS
    for t, group in TERMINAIS.items():
        freq = sum(1 for n in spins[:35] if n in group)
        if freq:
            for n in group:
                scores[n] += 0.03 * freq

    # 4) CAVALOS
    for cavalo in CAVALOS:
        freq = sum(1 for n in spins[:35] if n in cavalo)
        if freq:
            for n in cavalo:
                scores[n] += 0.04 * freq

    # 5) DEZENA DOS 20
    freq20 = sum(1 for n in spins[:35] if n in DEZENA_20)
    for n in DEZENA_20:
        scores[n] += 0.05 * freq20

    # 6) PROTEÇÃO ZERO
    if ZERO_FORCE:
        scores[0] += 0.6

    # ======================
    # SELEÇÃO FINAL
    # ======================
    ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    puxando = [n for n,_ in ordered[:TOP_N]]

    if ZERO_FORCE and 0 not in puxando:
        puxando[-1] = 0

    gatilhos = puxando[:TOP_TRIGGERS]

    return {
        "puxando": puxando,
        "gatilhos": gatilhos
    }


def process_roulette(roulette, numbers):


    if len(numbers) < 100:
        return None

    resultado = analyze(numbers[:100])

    if not resultado:
        return None

    gatilhos = resultado["gatilhos"]
    puxando = resultado["puxando"]

    if not gatilhos or not puxando:
        return None
    

    if numbers[0] not in gatilhos:
        return None
    

    

    c2 = Counter(numbers[1:4])
    total = sum(c2[n] for n in gatilhos)  


    if total > 0:

        print(f"Gatilho cancelado por ter menos de {total} números seguidos no puxando")
        return None

    bets = [*puxando]
    bets.insert(0, 0)
    bets = sorted(set(bets))

    return {
            "roulette_id": roulette['slug'],
            "roulette_name" : roulette["name"],
            "roulette_url" : roulette["url"],
            "pattern" : "CHAT",
            "triggers": [*gatilhos],
            "targets": bets,
            "bets": bets,
            "passed_spins" : 0,
            "spins_required" : 0,
            "spins_count": 0,
            "gales" : 7,
            "score" : total,
            "snapshot":numbers[:10],
            "status":"processing",
            "message" : "Gatilho encontrado!",
            "tags" : [],
        }


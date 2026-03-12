from patterns.ml_estelar.predict_20 import pick_20_numbers
from collections import Counter


# ===== Parâmetros da estratégia de contagem =====
COUNT_WINDOW = 200        # tamanho da janela de contagem (últimas 200 rodadas)
COUNT_THRESHOLD = 3       # mínimo de ocorrências para liberar sinal (ajuste aqui)
REQUIRE_ANY = True        # True = libera se QUALQUER número atingir o threshold; False = (modo alternativo) segurar

def _count_targets_in_window(numbers, targets, window=COUNT_WINDOW):
    """
    numbers: lista onde numbers[0] é o MAIS RECENTE.
    targets: lista de números sugeridos (18 ints).
    window: quantas últimas rodadas considerar.

    Retorna um dict {num_alvo: contagem} só para os alvos.
    """
    # recorte das últimas 'window' rodadas (mais recente no início)
    recents = numbers[:window] if window > 0 else numbers
    cnt = Counter(recents)

    # retorna só as contagens dos alvos
    return {n: cnt.get(n, 0) for n in targets}

def process_roulette(roulette, numbers) :

    if len(numbers) < 150 :
        return None
    
    res = pick_20_numbers(roulette["slug"], ",".join(str(n) for n in numbers[::-1]))

    print(res)
    targets_all = res["suggested_numbers"]
    nums = targets_all[:18]  # força 18 números

    # (opcional) ordena os alvos por quem mais apareceu na janela (só para estética/telemetria)
    nums_sorted = sorted(set(nums))

    print(nums)

    return {
            "roulette_id": roulette['slug'],
            "roulette_name" : roulette["name"],
            "roulette_url" : roulette["url"],
            "pattern" : "PULADA",
            "triggers":[numbers[0]],
            "targets": nums_sorted,
            "bets":nums_sorted,
            "passed_spins" : 0,
            "spins_required" : 0,
            "spins_count": 0,
            "snapshot":numbers[:50],
            "gales" : 2,
            "status":"processing",
            "message": "Gatilho encontrado!",
            "tags": [],  # Adicionando as tags coletadas
    }
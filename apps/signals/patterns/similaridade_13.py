from helpers.utils.get_mirror import get_mirror
from helpers.utils.get_neighbords import get_neighbords

ESPELHOS = {
    1: [10], 2: [20, 22], 3: [30], 6: [9], 9: [6], 10: [1], 11: [11],
    12: [21], 13: [31], 16: [19], 19: [16], 20: [2, 22], 21: [12],
    22: [2, 20], 23: [32], 26: [29], 29: [26], 30: [3], 31: [13],
    32: [23],
}

def process_roulette(roulette, numbers) :
    if len(numbers) < 20 :
        return None
    
    trigger = numbers[0]

    ocorrencias = [i for i, n in enumerate(numbers) if n == trigger]

    if len(ocorrencias) < 6:
        print(f"❌ SINAL NÃO GERADO: Menos de 5 ocorrências do gatilho {len(ocorrencias)} encontradas para análise.")
        return None
    
    grupos_similaridade = []

    
    for idx_ocorrencia in ocorrencias[1:6] :

        # Garante que não haverá index fora dos limites
        start_combo1 = idx_ocorrencia + 1
        end_combo1 = start_combo1 + 10
        combo1 = numbers[start_combo1:end_combo1]

        # Para pegar o "antes", a posição inicial não pode ser menor que 0
        start_combo2 = max(0, idx_ocorrencia - 10)
        end_combo2 = idx_ocorrencia
        combo2 = numbers[start_combo2:end_combo2]

        # Encontra os similares entre os dois combos
        similares = set(combo1) & set(combo2)
        grupos_similaridade.append(similares)

    alvos = set()
    protecoes = set()
    for grupo in grupos_similaridade:
        alvos.update(grupo)

    if not alvos:
        print(f"❌ SINAL NÃO GERADO: Nenhuma similaridade encontrada entre os combos nas 5 últimas ocorrências.")
        return

    if 0 not in alvos:
        alvos.add(0)

    for alvo in alvos:
        protecoes.update(ESPELHOS.get(alvo, []))
    protecoes = protecoes - alvos

    alvos_completos = alvos.union(protecoes)
    total_fichas = len(alvos_completos)

    bet = [*protecoes, *alvos]

    bet = sorted(set(bet))

    total_fichas = len(bet)

    if (13 == total_fichas):

        return {
                "roulette_id": roulette['slug'],
                "roulette_name" : roulette["name"],
                "roulette_url" : roulette["url"],
                "pattern" : "SIMILARIDADE_13",
                "triggers":[trigger],
                "targets":[*bet],
                "bets": bet,
                "passed_spins" : 0,
                "spins_required" : 0,
                "attempts" : 0,
                "spins_count": 0,
                "gales" : 4,
                "score" : 0,
                "snapshot":numbers[:10],
                "status":"monitoring",
                "message" : "Gatilho encontrado!",
                "tags" : [],
                }
    
    return None

from helpers.utils.get_mirror import get_mirror
from helpers.utils.get_neighbords import get_neighbords
from helpers.classificador import ClassificadorProximidade


ESPELHOS = {
    1: [10], 2: [20, 22], 3: [30], 6: [9], 9: [6], 10: [1], 11: [11],
    12: [21], 13: [31], 16: [19], 19: [16], 20: [2, 22], 21: [12],
    22: [2, 20], 23: [32], 26: [29], 29: [26], 30: [3], 31: [13],
    32: [23],
}

def process_roulette(roulette, numbers) :
    if len(numbers) < 20 :
        return None
    
    trigger =  numbers[0]

    historico_invertido = list(reversed(numbers))    
    ocorrencias = [i for i, n in enumerate(historico_invertido) if n == trigger]

    if len(ocorrencias) < 4:
        print(f"❌ SINAL NÃO GERADO: Menos de 5 ocorrências do gatilho {len(ocorrencias)} encontradas para análise.")
        return None
    
    grupos_similaridade = []

    
    for idx_ocorrencia in ocorrencias[1:3] :

        # Garante que não haverá index fora dos limites
        start_combo1 = idx_ocorrencia + 1
        end_combo1 = start_combo1 + 15
        combo1 = historico_invertido[start_combo1:end_combo1]

        # Para pegar o "antes", a posição inicial não pode ser menor que 0
        start_combo2 = max(0, idx_ocorrencia - 15)
        end_combo2 = idx_ocorrencia
        combo2 = historico_invertido[start_combo2:end_combo2]

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

    for alvo in alvos:
        protecoes.update(ESPELHOS.get(alvo, []))
    protecoes = protecoes - alvos

    alvos_completos = alvos.union(protecoes)
    total_fichas = len(alvos_completos)

    bet = [*protecoes, *alvos]

    bet = sorted(set(bet))

    total_fichas = len(bet)


    classificador = ClassificadorProximidade(peso_principal = 2.5,
    peso_vizinhos = 1.4,
    peso_vizinhos1 = 1.2,
    peso_duzia = 0.5,
    peso_cor = 0,
    peso_puxada = 2,
    qtd_puxada = 10,
    decaimento = 0.5)

    for number in numbers[:50]:
        classificador.adicionar_numero(number)

    ranking = classificador.get_ranking()[:20]

    numeros = [num for num, _ in ranking]

    # --- quantos de bet estão em numeros ---
    numeros_set = set(numeros)

    presentes = [n for n in bet if n in numeros_set]  # mantém a ordem de 'bet'
    qtd_presentes = len(presentes)
    perc_presentes = (qtd_presentes / len(bet)) * 100 if bet else 0.0

    if perc_presentes < 30 :
        return None


    if (10 == total_fichas):

        return {
                "roulette_id": roulette['slug'],
                "roulette_name" : roulette["name"],
                "roulette_url" : roulette["url"],
                "pattern" : f"SIMILARIDADE_{total_fichas}",
                "triggers":[trigger],
                "targets":[*bet],
                "bets": bet,
                "passed_spins" : 0,
                "spins_required" : 0,
                "attempts" : 0,
                "spins_count": 0,
                "gales" : 16,
                "score" : qtd_presentes,
                "snapshot":numbers[:10],
                "status":"processing",
                "message" : "Gatilho encontrado!",
                "tags" : [],
                }
    
    return None

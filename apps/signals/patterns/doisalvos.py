from helpers.utils.filters import first_index_after, is_consecutive
from helpers.utils.get_neighbords import get_neighbords, get_neighbords_color
from helpers.utils.get_mirror import get_mirror

from collections import Counter


def process_roulette(roulette, numbers):
    # Requer pelo menos 100 resultados
    if len(numbers) < 100:
        return None

    # Observação importante:
    # Pelo seu fluxo anterior, o MAIS RECENTE está no topo (index 0).
    # Portanto, para pegar os ÚLTIMOS 100 (mais recentes primeiro), use numbers[:100].
    # (Antes você estava usando [-50:], além de só 50 elementos – isso explica o "sempre 50/15".)
    ultimos_100 = numbers[:100]

    # Contar as ocorrências preservando multiplicidades
    contagem = Counter(ultimos_100)

    # Top 30 por frequência
    bet = []
    contagem_30 = 0
    for numero, vezes in contagem.most_common(25):
        # debug opcional:
        # print(f"{numero} -> {vezes}")
        contagem_30 += vezes
        bet.append(numero)

    # debug opcional:
    print("Soma top 25 (de 100):", contagem_30)

    tag = f'soma_{contagem_30}'

    p0 = numbers[0]  # mais recente

    if contagem_30 in [68, 69, 71, 73, 74] :

        return {
            "roulette_id": roulette["slug"],
            "roulette_name": roulette["name"],
            "roulette_url": roulette["url"],
            "pattern": "PUXADA",
            "triggers": [p0],
            "targets": [p0],
            "bets": bet,  # 30 números mais frequentes nos últimos 100
            "passed_spins": 0,
            "spins_required": 0,
            "spins_count": 0,
            "snapshot": numbers[:100],  # mantém a mesma convenção: mais recentes primeiro
            "status": "processing",
            "gales": 2,
            "message": "Gatilho encontrado!",
            "tags": [tag],
        }
    

from helpers.utils.filters import first_index_after, is_consecutive

from helpers.utils.get_neighbords import get_neighbords

from helpers.utils.get_mirror import get_mirror


def process_roulette(roulette, numbers) :


    if len(numbers) < 50 :
        print('Números insuficientes')
        return None

    p0  = numbers[0]

    print(p0)

    indice1 = first_index_after(numbers, p0, 2)

    if indice1 is None :
        print('Indice 1 não encontrado')
        return None

    indice2 = first_index_after(numbers, p0, indice1 + 1)

    if indice2 is None :
        print('Indice 2 não encontrado')
        return None
    

    bet1 = numbers[indice1:indice1+4]
    bet2 = numbers[indice2:indice2+4]

    bet = [*bet1, *bet2]   
    vizinhos = [v for vz in bet for v in get_neighbords(vz)] 

    bet.extend(vizinhos)

    mirror_list = [m for n in bet for m in get_mirror(n)]

    bet.extend(mirror_list)

    bet.insert(0, 0)

    bet = sorted(set(bet))

    if len(bet) > 20 :
        return None

    return {
        "roulette_id": roulette["slug"],
        "roulette_name": roulette["name"],
        "roulette_url": roulette["url"],
        "pattern": "ALINHAMENTO-TOTAL",
        "triggers": [numbers[0]],  # zero mais recente
        "targets": [*bet],
        "bets": bet,
        "passed_spins": 0,
        "spins_required": 0,
        "spins_count": 0,
        "snapshot": numbers,
        "status": "processing",
        "gales" : 2,
        "message": f"Gatilho ativado! base de números : {numbers[indice1], numbers[indice2]}",
        "tags": [],
    }

    return None
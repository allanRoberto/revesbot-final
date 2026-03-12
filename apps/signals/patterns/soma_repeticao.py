from helpers.utils.filters import first_index_after, soma_digitos
from helpers.utils.get_figure import get_figure


def process_roulette(roulette, numbers) :

    if len(numbers) < 10 :
        return None

    idxs = [0,1,2,3,4,5,6,7,8,9]

    p0, p1, p2, p3, p4, p5, p6, p7, p8, p9 = [numbers[i] for i in idxs]

    
    paread_index = first_index_after(numbers, p0, 1)

    if paread_index == None :
        return None

    paread_num = numbers[paread_index + 1]

    if(p0 == paread_num) :
        return None

    if(soma_digitos(p0) == soma_digitos(paread_num)) :
        figures = get_figure(soma_digitos(p0))

        bet = figures

        
        return {
            "roulette_id": roulette['slug'],
            "roulette_name" : roulette["name"],
            "roulette_url" : roulette["url"],
            "pattern" : "SOMA_REPETICAO",
            "triggers":[p0],
            "targets":[*bet],
            "bets":bet,
            "passed_spins" : 0,
            "spins_required" : 0,
            "spins_count": 0,
            "snapshot":numbers[:50],
            "status":"processing",
            "message": "Gatilho encontrado!",
            "tags": [],  # Adicionando as tags coletadas
    }
    
    
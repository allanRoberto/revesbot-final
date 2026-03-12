from helpers.utils.filters import first_index_after
from helpers.utils.get_mirror import get_mirror
from helpers.utils.get_neighbords import get_neighbords
from helpers.utils.get_figure import get_figure


def process_roulette(roulette, numbers) :
    idxs = (0,1,2)

    p0, p1, p2 = [numbers[i] for i in idxs]


    indice1 = first_index_after(numbers, p0, 2)

    if indice1 == None :
        return None
    
    if indice1 < 10 :
        return None

    check1 = numbers[indice1 + 1]
    check2 = numbers[indice1 + 2]
    check3 = numbers[indice1 - 1]
    check4 = numbers[indice1 - 2]

    if p1 in [check1, check3] :
        check2_mirror = get_mirror(check2)
        check2_neighbords = get_neighbords(check2)
        check2_figure = get_figure(check2)
        check4_mirror = get_neighbords(check4)
        check4_neighbords = get_neighbords(check4)
        check4_figure = get_figure(check4)

        bet = [*check2_mirror, *check2_neighbords, *check2_figure, check2, *check4_mirror, *check4_neighbords, *check4_figure, check4]

        return {
                "roulette_id": roulette['slug'],
                "roulette_name" : roulette["name"],
                "roulette_url" : roulette["url"],
                "pattern" : "FALTANTE",
                "triggers":[numbers[0]],
                "targets":[*bet],
                "bets":bet,
                "passed_spins" : 0,
                "spins_required" : 0,
                "spins_count": 0,
                "gales" : 3,
                "snapshot":numbers[:50],
                "status":"processing",
                "message": "Gatilho encontrado!",
                "tags": [],  # Adicionando as tags coletadas
        }
    elif p1 in [check2, check4] :
        check1_mirror = get_mirror(check1)
        check1_neighbords = get_neighbords(check1)
        check1_figure = get_figure(check1)
        check3_mirror = get_neighbords(check3)
        check3_neighbords = get_neighbords(check3)
        check3_figure = get_figure(check3)

        bet = [*check1_mirror, *check1_neighbords, *check1_figure, check1, *check3_mirror, *check3_neighbords, *check3_figure, check3]


        return {
                "roulette_id": roulette['slug'],
                "roulette_name" : roulette["name"],
                "roulette_url" : roulette["url"],
                "pattern" : "FALTANTE",
                "triggers":[numbers[0]],
                "targets":[*bet],
                "bets":bet,
                "passed_spins" : 0,
                "spins_required" : 0,
                "spins_count": 0,
                "gales" : 3,
                "snapshot":numbers[:50],
                "status":"processing",
                "message": "Gatilho encontrado!",
                "tags": [],  # Adicionando as tags coletadas
        }

    return None
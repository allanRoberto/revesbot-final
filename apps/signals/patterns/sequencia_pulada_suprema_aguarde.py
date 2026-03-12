from helpers.utils.filters import is_skipped_sequence, soma_digitos, is_consecutive
from helpers.utils.get_figure import get_figure
from helpers.utils.get_neighbords import get_neighbords

def process_roulette(roulette, numbers) :

    if len(numbers) < 10 :
        return None

    check0 = numbers[2]
    check1 = numbers[3]

      # Pré‑condição da lógica original
    if not is_skipped_sequence(check0, check1):
        return None  # nada a filtrar
    
    check0_figure = get_figure(soma_digitos(check0))
    check1_figure = get_figure(soma_digitos(check1))

    if check0 > check1 : 
        check2_figure = get_figure(soma_digitos(check0 - 1))
    else :
        check2_figure = get_figure(soma_digitos(check0 + 1))
    
    bet  = [*check1_figure, *check0_figure, *check2_figure]

    bet = sorted(set(bet))

    numbers1_neighbords = get_neighbords(numbers[1])
    numbers4_neighbords = get_neighbords(numbers[4])

    if(numbers[1] == numbers[4]) :
        return None
    
    if(is_consecutive(numbers[1], numbers[4])) :
        return None
    
    if numbers[1] in numbers4_neighbords or numbers[4] in numbers1_neighbords :
        return None


    return {
            "roulette_id": roulette['slug'],
            "roulette_name" : roulette["name"],
            "roulette_url" : roulette["url"],
            "pattern" : "PULADA AGUARDANDO GATILHO DE TRÁS",
            "triggers":[numbers[4]],
            "targets":[*bet],
            "bets":bet,
            "passed_spins" : 0,
            "spins_required" : 0,
            "spins_count": 0,
            "snapshot":numbers[:10],
            "status":"waiting",
            "gales" : 3,
            "message": "Gatilho encontrado!",
            "tags": [],  # Adicionando as tags coletadas
    }
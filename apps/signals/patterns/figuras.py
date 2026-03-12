from helpers.utils.filters import (
    soma_digitos,
    is_consecutive,
    appears_in_slice
)

from helpers.utils.get_neighbords import get_neighbords

from filters.run_all_filters import run_all_filters

from helpers.utils.get_figure import get_figure

def check_inversion(numbers, bet) :
      # elementos imediatamente antes do gatilho
        window = numbers[1 : 5]

        # verifica interseção de sets para eficiência
        bets_set = set(bet or [])
        common = bets_set.intersection(window)

        return next(iter(common)) if common else None

def process_roulette(roulette, numbers) :

    if(len(numbers) < 10) :
        return None

    
    idxs = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9)
    p0, p1, p2, p3, p4, p5, p6, p7, p8, p9 = [numbers[i] for i in idxs] 

    if(p0 == 22 and p1 == 22) :

        figures1 = get_figure(8)
        figures2 = get_figure(1)
        figures3 = get_figure(9)

        figures = [8, 10, 9,  *figures1, *figures2, *figures3]

        

        bet = [*figures]

        

        for terminal_number in figures :
                neighbords = get_neighbords(terminal_number)

        bet.insert(0,0)

        bloqueado, tags = run_all_filters(numbers)

        return {
            "roulette_id": roulette['slug'],
            "roulette_name" : roulette["name"],
            "roulette_url" : roulette["url"],
            "pattern" : "FIGURAS",
            "triggers":[p0],
            "targets":[8, 10],
            "bets":bet,
            "passed_spins" : 0,
            "spins_required" : 0,
            "spins_count": 0,
            "snapshot":numbers[:50],
            "status":"processing",
            "message": "Gatilho encontrado!",
            "tags": tags,  # Adicionando as tags coletadas
        }


    
    return None
from helpers.utils.filters import first_index_after, get_terminal, get_neighbords, get_numbers_by_terminal
from helpers.utils.get_figure import get_figure
import time

from datetime import datetime


from typing import Iterable, Optional, Set, FrozenSet

GRUPOS: list[Set[int]] = [
    {1, 4, 7},
    {2, 5, 8},
    {0, 3, 6},
    {3, 6, 9},
]

# DEFINIÇÃO DOS CAVALOS
CAVALOS = {
    "147": [1, 11, 21, 31, 4, 14, 24, 34, 7, 17, 27],
    "258": [2, 12, 22, 32, 5, 15, 25, 35, 8, 18, 28],
    "0369": [0, 10, 20, 30, 3, 13, 23, 33, 6, 16, 26, 36, 9, 19, 29]
}

# MAPEAMENTO DE NÚMERO PARA CAVALO
def obter_cavalo_do_numero(numero):
    """Retorna o cavalo ao qual o número pertence."""
    for cavalo, numeros in CAVALOS.items():
        if numero in numeros:
            return cavalo
    return None


def numero_faltante(grupos: Iterable[Set[int]], a: int, b: int) -> Optional[int]:
    
    par: FrozenSet[int] = frozenset((a, b))
    for g in grupos:
        if par.issubset(g):
            faltantes = g - set(par)
            return next(iter(faltantes))
    return None

def process_roulette(roulette, numbers) :


    if len(numbers) < 100 :
        return None
    
    gatilho = numbers[0]

    if gatilho == numbers[1] :
        return None

    indice1 = first_index_after(numbers, gatilho, 1);

    if indice1 is None :
        return None
    

    cavalo_indice1 = numbers[indice1 - 1]

    indice2 = first_index_after(numbers, gatilho, indice1 + 1)

    if indice2 is None :
        return None
    
    indice3 = first_index_after(numbers, gatilho, indice2 + 1)

    if indice3 is None :
        return None
    
    indice4 = first_index_after(numbers, gatilho, indice3 + 1)



    cavalo_indice2 = numbers[indice2 - 1]



    if not indice3 is None :
        cavalo_indice3 = numbers[indice3 - 1]
        terminal_cavalo3 = get_terminal(cavalo_indice3)
    else : 
        terminal_cavalo3 = "Não existe"


    if not indice4 is None :
        cavalo_indice4 = numbers[indice4 - 1]
        terminal_cavalo4 = get_terminal(cavalo_indice4)
    else : 
        terminal_cavalo4 = "Não existe"

    mesmocavalo1 = "NAO"
    mesmocavalo2 = "NAO"

    terminal_cavalo1 = get_terminal(cavalo_indice1)
    terminal_cavalo2 = get_terminal(cavalo_indice2)

    if terminal_cavalo1 == terminal_cavalo2 : 
        return None

    cavalo_faltante = numero_faltante(GRUPOS, terminal_cavalo1, terminal_cavalo2)

    if cavalo_faltante is None:
        return None
    
    if cavalo_faltante in numbers[1:4] :
        return None

    cavalo2 = obter_cavalo_do_numero(terminal_cavalo3)
    cavalo3 = obter_cavalo_do_numero(terminal_cavalo4)

    if cavalo2 == cavalo3 :
        mesmocavalo2 == "SIM"
        return None 


    if cavalo_faltante in numbers[1:4] :
        return None

    figuras_faltantes = get_figure(cavalo_faltante)

    bet = []

    vizinhos_list = [m for n in figuras_faltantes for m in get_neighbords(n)] 

    bet.extend(vizinhos_list)
    bet.extend(figuras_faltantes)

    bet.insert(0,0)

    if cavalo_faltante in [0,3,6,9] :
        bet = [0, 10, 20, 30, 3, 13, 23, 33, 6, 16, 26, 36, 9, 19, 29]
    else :
        return None
    


    bet = sorted(set(bet))
    
    
    created_at = int(time.time())


    return {
        "roulette_id": roulette['slug'],
        "roulette_name" : roulette["name"],
        "roulette_url" : roulette["url"],
        "pattern" : f"CAVALO_FALTANTE",
        "triggers": numbers[0],
        "targets":[*bet],
        "bets": bet,
        "passed_spins" : 0,
        "spins_required" : 0,
        "spins_count": 0,
        "gales" : 3,
        "score" : 0,
        "snapshot":numbers[:200],
        "status": "processing",
        "message" : "Gatilho encontrado! ",
        "tags" : [],
        "temp_state" : None,
        "created_at" : created_at,
        "timestamp" : created_at
    }




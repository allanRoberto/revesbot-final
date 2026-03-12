from helpers.utils.filters import first_index_after, is_consecutive, get_mirror

from datetime import datetime

# DEFINIÇÃO DOS CAVALOS
CAVALOS = {
    "147": [0, 1, 11, 21, 31, 4, 14, 24, 34, 7, 17, 27],
    "258": [0, 2, 12, 22, 32, 5, 15, 25, 35, 8, 18, 28],
    "0369": [0, 10, 20, 30, 3, 13, 23, 33, 6, 16, 26, 36, 9, 19, 29]
}

# MAPEAMENTO DE NÚMERO PARA CAVALO
def obter_cavalo_do_numero(numero):
    """Retorna o cavalo ao qual o número pertence."""
    for cavalo, numeros in CAVALOS.items():
        if numero in numeros:
            return cavalo
    return None


def _build_signal(*, roulette: dict, numbers: list[int], trigger: int, target_a: list, bet: list[int], pattern: str) -> dict:
    created_at = int(datetime.now().timestamp())

    return {
        "roulette_id": roulette["slug"],
        "roulette_name": roulette["name"],
        "roulette_url": roulette["url"],
        "pattern": pattern,
        "triggers": trigger,
        "targets": [*target_a],
        "bets": bet,
        "passed_spins": 0,
        "spins_required": 0,
        "spins_count": 0,
        "gales": 3,
        "score": 0,
        "snapshot": numbers[:200],
        "status": "processing",
        "message": "Gatilho encontrado! ",
        "tags": [],
        "temp_state": None,
        "created_at": created_at,
        "timestamp": created_at,
    }

def process_roulette(roulette, numbers) :

    base = numbers[0]

    if is_consecutive(numbers[0], numbers[1]) :
        return None
    
    if numbers[1] >= 1 and numbers[1] <= 9 :
        return None 
    


    if base >= 0 and base <= 9 :
        
        cavalo = obter_cavalo_do_numero(base)

        indice = first_index_after(numbers, base, 1)

        if indice <= 5 :
            print("Muito próximo")
            return None


        window_check = numbers[indice - 3 : indice]

        pagou = bool(set(CAVALOS[cavalo]) & set(window_check))

        if pagou :
            print("Pagou na ocorrência anterior")
            return None


        bet = CAVALOS[cavalo]

        mirror = get_mirror(base)

        bet.insert(0, base- 1)
        bet.insert(0, base + 1)

        bet.extend(mirror)

        bet = sorted(set(bet))

        return _build_signal(
                roulette=roulette,
                numbers=numbers,
                trigger=numbers[0],
                target_a=bet,
                bet=[*bet],
                pattern="PUXOU_CAVALO_TODOS",
            )

    else :
        print(f"Não é o número {base}")
        return None


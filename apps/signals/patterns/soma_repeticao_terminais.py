from helpers.utils.filters import soma_digitos, get_terminal, get_numbers_by_terminal, get_neighbords
from helpers.utils.get_figure import get_figure
from datetime import datetime


def _build_signal(*, roulette: dict, numbers: list[int], trigger: int, target: int, bet: list[int], pattern: str) -> dict:
    created_at = int(datetime.now().timestamp())

    return {
        "roulette_id": roulette["slug"],
        "roulette_name": roulette["name"],
        "roulette_url": roulette["url"],
        "pattern": pattern,
        "triggers": trigger,
        "targets": [target],
        "bets": bet,
        "passed_spins": 0,
        "spins_required": 0,
        "spins_count": 0,
        "gales": 20,
        "score": 0,
        "snapshot": numbers[:200],
        "status": "processing",
        "message": "Gatilho encontrado! ",
        "tags": [],
        "temp_state": None,
        "created_at": created_at,
        "timestamp": created_at,
    }

def _flatten_ints(value) -> list[int]:
    """Achata qualquer combinação de listas/tuplas/sets em uma lista de ints."""
    out: list[int] = []

    def walk(v):
        if v is None:
            return
        if isinstance(v, bool):
            # bool é subclass de int; não queremos tratar como número aqui
            return
        if isinstance(v, int):
            out.append(v)
            return
        if isinstance(v, (list, tuple, set)):
            for item in v:
                walk(item)
            return
        # ignora outros tipos silenciosamente (str/dict/etc)
        return

    walk(value)
    return out

def process_roulette(roulette, numbers) :


    t1 = get_terminal(numbers[0])
    t2 = get_terminal(numbers[1])

    if t1 == t2 :

        soma1 = soma_digitos(numbers[0])     
        soma2 = soma_digitos(numbers[1])


        print(soma1, soma2, soma1 + soma2)

        bet = []
        target = soma1 + soma2

        terminal = get_terminal(target)

        t1 = get_numbers_by_terminal(terminal)
        f1 = get_figure(terminal)

        bet.extend(_flatten_ints(t1))
        bet.extend(_flatten_ints(f1))


        vizinhos = [get_neighbords(n) for n in bet]
        bet.extend(_flatten_ints(vizinhos))
        bet = sorted(set(bet))


        return _build_signal(
                roulette=roulette,
                numbers=numbers,
                trigger=numbers[1],
                target=terminal,
                bet=bet,
                pattern="SOMA_REPETICAO_TERMINALS",
            )
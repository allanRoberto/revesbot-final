from helpers.utils.filters import get_terminal, get_numbers_by_terminal, get_mirror, get_neighbords, soma_digitos
from helpers.utils.get_figure import get_figure 

from datetime import datetime


def check_pattern(numbers: list[int]) -> tuple[bool, list[str]]:
    if len(numbers) < 6:
        return False, ["Lista precisa ter pelo menos 6 números (índices 0..5)."]

    terminals = [get_terminal(n) for n in numbers]
    errors: list[str] = []

    # =========================
    # 1️⃣ Regra base do padrão
    # terminals[1] == terminals[3]
    # =========================
    if terminals[1] != terminals[3]:
        errors.append("Base falhou: terminals[1] deve ser igual a terminals[3].")

    # =========================
    # 2️⃣ terminals[0] != terminals[1]
    # =========================
    if terminals[0] == terminals[1]:
        errors.append("Falha: terminals[0] não pode ser igual a terminals[1].")

    # =========================
    # 3️⃣ terminals[2] != terminals[3] e != terminals[1]
    # =========================
    if terminals[2] in (terminals[3], terminals[1]):
        errors.append("Falha: terminals[2] não pode ser igual a terminals[3] nem a terminals[1].")

    # =========================
    # 4️⃣ terminals[4] e terminals[5] != terminals[3]
    # =========================
    for i in (4, 5):
        if terminals[i] == terminals[3]:
            errors.append(f"Falha: terminals[{i}] não pode ser igual a terminals[3].")

    # =========================
    # 5️⃣ numbers[0], [2], [4], [5]
    # não podem ser espelho de numbers[1] ou numbers[3]
    # =========================
    forbidden_sources = (numbers[1], numbers[3])
    check_indexes = (0, 2, 4, 5)

    for i in check_indexes:
        mirrors = get_mirror(numbers[i])  # retorna lista ou []
        if any(src in mirrors for src in forbidden_sources):
            errors.append(
                f"Falha: numbers[{i}] ({numbers[i]}) é espelho de numbers[1] ou numbers[3]."
            )

    return (len(errors) == 0), errors


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


def process_roulette(roulette, numbers):

    print(numbers[0])

    ok, errors = check_pattern(numbers)

    if ok:
        terminal = get_terminal(numbers[1])
        targets = get_numbers_by_terminal(terminal)

        figuras = get_figure(terminal)

        # vizinhos vira lista (possivelmente aninhada)
        vizinhos = [get_neighbords(n) for n in targets]

        # Monta bet como lista plana de ints (sem listas internas)
        bet: list[int] = []
        bet.append(0)
        bet.extend(_flatten_ints(vizinhos))
        bet.extend(_flatten_ints(targets))
        bet.extend(_flatten_ints(figuras))

        # unique + ordena
        bet = sorted(set(bet))

        return _build_signal(
            roulette=roulette,
            numbers=numbers,
            trigger=numbers[1],
            target=terminal,
            bet=bet,
            pattern="ALTERNANCIA_TERMINAL",
        )

    else:
        print("Padrão não formado ❌")
        for e in errors:
            print("-", e)
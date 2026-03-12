from helpers.utils.filters import first_index_after, get_terminal

from datetime import datetime


# DEFINIÇÃO DOS CAVALOS
CAVALOS = {
    "147": [1, 11, 21, 31, 4, 14, 24, 34, 7, 17, 27],
    "258": [2, 12, 22, 32, 5, 15, 25, 35, 8, 18, 28],
    "0369": [0, 10, 20, 30, 3, 13, 23, 33, 6, 16, 26, 36, 9, 19, 29]
}


def obter_cavalo_do_numero(numero: int) -> str | None:
    """Retorna o cavalo ao qual o número pertence."""
    for cavalo, numeros in CAVALOS.items():
        if numero in numeros:
            return cavalo
    return None


def _is_terminal_trigger(a: int | None, b: int | None) -> tuple[bool, str | None]:
    """
    Verifica se dois números (a, b) formam gatilho de terminais:
      - mesmo terminal
      - números diferentes
      - pertencem ao mesmo cavalo
      - cavalo existe no dict e não é vazio
    Retorna (is_trigger, cavalo).
    """
    if a is None or b is None:
        return False, None

    if a == b:
        return False, None

    if get_terminal(a) != get_terminal(b):
        return False, None

    cav_a = obter_cavalo_do_numero(a)
    cav_b = obter_cavalo_do_numero(b)

    if not cav_a or cav_a != cav_b:
        return False, None

    bet = CAVALOS.get(cav_a, [])
    if not bet:
        return False, None

    return True, cav_a


def _paid_on(cavalo: str | None, value: int | None) -> bool:
    """Considera 'pagou' se o número que veio depois está dentro do cavalo (ou é 0)."""
    if cavalo is None or value is None:
        return False
    if value == 0:
        return True
    return value in CAVALOS.get(cavalo, [])


def process_roulette(roulette, numbers):
    if len(numbers) < 200:
        print('cancelou')
        return None

    base = numbers[0]
    print(base, roulette["slug"])


   

    # Coleta até 4 ocorrências do base (após o índice 0)
    indices: list[int] = []
    start_pos = 1
    for _ in range(4):
        idx = first_index_after(numbers, base, start_pos)
        if idx is None:
            break
        indices.append(idx)
        start_pos = idx + 1

    if len(indices) < 2:
        return None

    # n1..n4 = número associado à ocorrência (mesma convenção já usada antes: idx-1)
    # OBS: isso depende da ordem do seu histórico (recent_first vs old_first),
    # mas mantemos exatamente a lógica original do arquivo.
    pulled = []
    for idx in indices:
        if idx <= 0:
            pulled.append(None)
        else:
            pulled.append(numbers[idx - 1])

    n1 = pulled[0] if len(pulled) > 0 else None
    n2 = pulled[1] if len(pulled) > 1 else None
    n3 = pulled[2] if len(pulled) > 2 else None
    n4 = pulled[3] if len(pulled) > 3 else None

    # Gatilho atual (2 ocorrências anteriores)
    is_now, cav_now = _is_terminal_trigger(n1, n2)
    if not is_now or not cav_now:
        return None

    # Nova regra: evitar "rearmar" logo após um sinal ter pago.
    #
    # Exemplo:
    #   5>31, 5>21 (armou), depois 5 pagou em 27, e a próxima ocorrência 5>7 armaria de novo
    # Isso acontece porque (27,7) também formam o mesmo gatilho/cavalo, usando o número de "pagamento".
    #
    # Detectamos olhando a 3ª e 4ª ocorrência:
    # - Se (n2,n3) formou um gatilho e ele "pagou" em n1, então NÃO podemos armar usando (n1,n2).
    is_prev, cav_prev = _is_terminal_trigger(n2, n3)
    if is_prev and cav_prev == cav_now and _paid_on(cav_prev, n1):
        return None

    # Extra: mesma proteção um passo mais atrás (4ª ocorrência), para evitar cadeia de rearme.
    is_prev2, cav_prev2 = _is_terminal_trigger(n3, n4)
    if is_prev2 and cav_prev2 == cav_now and _paid_on(cav_prev2, n2):
        return None

    bet = CAVALOS.get(cav_now, [])
    if not bet:
        return None

    bet = [0, *bet]
    bet = sorted(set(bet))

    dt = datetime.now()
    created_at = int(dt.timestamp())

    status = "processing"

    tem_comum = bool(set(numbers[1:3]) & set(bet))
    if tem_comum:
        return None

    signal = {
        "roulette_id": roulette["slug"],
        "roulette_name": roulette["name"],
        "roulette_url": roulette["url"],
        "pattern": "TERMINAIS-PUXANDO",
        "triggers": numbers[0],
        "targets": [*bet],
        "bets": bet,
        "passed_spins" : 0,
        "spins_required" : 0,
        "spins_count": 0,
        "gales": 3,
        "score": 0,
        "snapshot": numbers[:200],
        "status": status,
        "message": "Gatilho encontrado!",
        "tags": [],
        "temp_state": None,
        "created_at": created_at,
        "timestamp": created_at,
    }

   

    return signal
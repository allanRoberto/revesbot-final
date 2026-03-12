from datetime import datetime

from helpers.utils.filters import first_index_after, get_neighbords, get_mirror, get_neighbords_color, is_consecutive, get_terminal


def _build_bet(*, target_a: int, target_b: int, confirm: int, include_confirm_mirrors: bool, include_confirm_neighbords : bool) -> list[int]:
    """Monta a lista final de apostas (bets) para o sinal."""

    bet_set: set[int] = set()

    # Nucleo dos alvos
    bet_set.update(get_neighbords(target_a))
    bet_set.update(get_mirror(target_a))
    bet_set.update(get_neighbords(target_b))
    bet_set.update(get_mirror(target_b))

    # Espelhos do confirmador (quando aplicavel)
    if include_confirm_mirrors:
        bet_set.update(get_mirror(confirm))

    if include_confirm_neighbords:
        bet_set.update(get_neighbords(confirm))

    # Base fixa da aposta
    bet_set.update({0, target_a, target_b, confirm})

    return sorted(bet_set)


def _build_signal(*, roulette: dict, numbers: list[int], trigger: int, target_a: int, target_b: int, confirm: int, bet: list[int], pattern: str) -> dict:
    created_at = int(datetime.now().timestamp())

    return {
        "roulette_id": roulette["slug"],
        "roulette_name": roulette["name"],
        "roulette_url": roulette["url"],
        "pattern": pattern,
        "triggers": trigger,
        "targets": [target_a, target_b],
        "bets": bet,
        "passed_spins": 0,
        "spins_required": 0,
        "spins_count": 0,
        "gales": 6,
        "score": 0,
        "snapshot": numbers[:200],
        "status": "processing",
        "message": "Gatilho encontrado! ",
        "tags": [],
        "temp_state": None,
        "created_at": created_at,
        "timestamp": created_at,
    }


def process_roulette(roulette, numbers):
    # Precisa de historico suficiente
    if len(numbers) < 300:
        return None
    
    base = numbers[0]
    n1 = numbers[1]
    n2 = numbers[2]
    n3 = numbers[3]
    n4 = numbers[4]

    t1 = get_terminal(n1)
    t2 = get_terminal(n2)
    t3 = get_terminal(n3)
    t4 = get_terminal(n4)

    indice = first_index_after(numbers, base, 1)

    if indice < 10 :
        return None

    if not indice is None :

        # Confirmacao e gatilho vem do "agora"
        confirm = numbers[indice - 1]
        trigger = numbers[indice]
        confirm_2 = numbers[indice + 1]

        # Filtro: gatilho nao pode ser igual a confirmacao
        if trigger == confirm:
            return None

        confirm_mirrors = set(get_mirror(confirm))
        confirm_neighbords = set(get_neighbords(confirm))

        # Busca ate 2 ocorrencias anteriores do gatilho (depois do indice 1)
        indices: list[int] = []
        start_pos = indice + 2
        for _ in range(2):
            idx = first_index_after(numbers, trigger, start_pos)
            if idx is None:
                break
            indices.append(idx)
            start_pos = idx + 1

        if not indices:
            return None

        current_trigger_index = 1

        for idx in indices:
            # Filtro: distancia minima entre a ocorrencia atual do gatilho (indice 1)
            # e a ocorrencia antiga que forma o padrao (idx)
            if (idx - current_trigger_index) < 12:
                continue

            # Precisa caber o padrao [trigger, target, confirmador]
            if idx + 2 >= len(numbers):
                continue

            target_a = numbers[idx + 1]
            target_b = numbers[idx + 2]
            third = numbers[idx + 3]

            # Decide qual tipo de formacao aconteceu (e qual "pattern" usar)
            pattern = None
            include_confirm_mirrors = False
            include_confirm_neighbords = False
            match_kind = None

            if third == confirm:
                match_kind = "DIRECT"
                pattern = "TRES-FICHAS"
                include_confirm_mirrors = False
            elif third in confirm_mirrors:
                match_kind = "MIRROR"
                pattern = "TRES-FICHAS-ESPELHO"
                include_confirm_mirrors = True
            elif third in confirm_neighbords:


                match_kind = "NEIGHBORS"
                pattern = "TRES-FICHAS-VIZINHOS"
                include_confirm_mirrors = False
                include_confirm_neighbords = True
            else:
                continue

            # Aqui entram os filtros comuns (voce adiciona 1 vez so)


            vizinhos_target_0 = set(get_neighbords(target_a))
            vizinhos_target_1 = set(get_neighbords(target_b))

            vizinhos_target = [*vizinhos_target_0, *vizinhos_target_1]

            # Filtro especifico do DIRECT (mantem o comportamento original: aborta o sinal)
            if match_kind == "DIRECT":
                if confirm in vizinhos_target:
                    return None
                if trigger in vizinhos_target:
                    return None

            if is_consecutive(target_a, confirm) or is_consecutive(target_b, confirm):
                return None
            
            if is_consecutive(target_a, confirm_2) or is_consecutive(target_b, confirm_2):
                return None
            
            if target_a == confirm_2 or target_b == confirm_2:
                return None


            if is_consecutive(t1, t2) :
                return None
            
            if t1 == t2 :
                return None
            
            if t1 == t3 :
                return None
            

            

            
            
            bet = _build_bet(target_a=target_a, target_b=target_b, confirm=confirm, include_confirm_mirrors=include_confirm_mirrors, include_confirm_neighbords=include_confirm_neighbords)
            
            
            tem_comum = bool(set(numbers[1:3]) & set(bet)) 

            

            if tem_comum :
                return None
            
            
            return _build_signal(
                roulette=roulette,
                numbers=numbers,
                trigger=trigger,
                target_a=target_a,
                target_b=target_b,
                confirm=confirm,
                bet=bet,
                pattern=pattern,
            )

        return None

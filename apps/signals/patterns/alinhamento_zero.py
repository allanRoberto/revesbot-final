from helpers.utils.get_mirror import get_mirror
from helpers.utils.get_neighbords import get_neighbords
from helpers.utils.filters import soma_digitos, first_index_after
from collections import Counter


def process_roulette(roulette, numbers):
    """
    Estratégia: quando o número mais recente (numbers[0]) é 0, buscamos o próximo 0
    após a posição 2. Se houver, usamos os 3 números imediatamente anteriores a esse
    segundo 0 como base da aposta, expandindo para vizinhos e espelhos.
    """

    # Validações básicas
    if not numbers or len(numbers) < 3:
        return None

    # Só processa se o número mais recente for 0
    if numbers[1] != 0:
        return None
    
    if numbers[0] == 0 :
        return None

    # Próximo zero depois do índice 2
    i = first_index_after(numbers, 0, 2)
    if i is None:
        return None

    # Se quiser exigir uma distância mínima do próximo zero
    if i < 30:
        return None

    # Evita casos em que os próximos 2 números imediatos já sejam 0
    # (mantém sua regra original, mas com proteção de tamanho)
    if len(numbers) >= 3 and (numbers[2] == 0 or numbers[3] == 0):
        return None

    # >>> CORREÇÃO PRINCIPAL <<<
    # Pegar os 3 números IMEDIATAMENTE ANTERIORES ao zero encontrado em i
    # (garante que i-3 não seja negativo; sua regra de i<10 já cobre, mas deixo robusto)


    nums = [n for n in numbers[i-3:i+3] if n != 0]


    if 0 in numbers[i+1:i+5] :

        print("zero próximo")
        return None

    if not nums:
        return None

    # Monta aposta a partir dos 3 números-base
    bet = []
    for n in nums:
        mirror = get_mirror(n)
        vizinhos = get_neighbords(n)
        bet.extend([n-1, n, n+1, *mirror, *vizinhos])

    # Adiciona vizinhos dos números-base
    vizinhos_list = [m for n in bet for m in get_neighbords(n)]
    #bet.extend(vizinhos_list)

    # Adiciona espelhos dos números atuais da bet (base + vizinhos)
    mirror_list = [m for n in bet for m in get_mirror(n)]
    #bet.extend(mirror_list)

    # Remove duplicatas, mantém apenas valores válidos da roleta e ordena
    bet = sorted({n for n in bet if isinstance(n, int) and 0 <= n <= 36})

    if not bet:
        return None


    return {
        "roulette_id": roulette["slug"],
        "roulette_name": roulette["name"],
        "roulette_url": roulette["url"],
        "pattern": "ALINHAMENTO-ZERO",
        "triggers": [numbers[1]],  # zero mais recente
        "targets": [*bet],
        "bets": bet,
        "passed_spins": 0,
        "spins_required": 0,
        "spins_count": 0,
        "snapshot": numbers,
        "status": "waiting",
        "message": f"Gatilho ativado! base de números : {nums}",
        "tags": [],
    }

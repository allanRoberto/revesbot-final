from helpers.utils.get_mirror import get_mirror
from helpers.utils.get_neighbords import get_neighbords, get_neighbords_color
from helpers.utils.get_figure import get_figure
from helpers.utils.filters import first_index_after, soma_digitos, get_numbers_by_terminal, get_terminal
from helpers.classificador import ClassificadorProximidade

def process_roulette(roulette, numbers):
    """
    Estratégia: quando o número mais recente (numbers[0]) é 0, buscamos o próximo 0
    após a posição 2. Se houver, usamos os 3 números imediatamente anteriores a esse
    segundo 0 como base da aposta, expandindo para vizinhos e espelhos.
    """
    # Validações básicas
    if not numbers or len(numbers) < 3:
        print('Números insuficientes')
        return None
    
    base = numbers[0]

    i = first_index_after(numbers, base, 11)
    if i is None:
        return None

    i2 = first_index_after(numbers, base, i)

    if i2 is None:
        return None

    nums = [n for n in numbers[i2:i2+3] if n != 0]

    if not nums:
        return None

    # Monta aposta a partir dos 3 números-base
    bet = []
    for n in nums:
        mirror = get_mirror(n)
        vizinhos = get_neighbords(n, 1)
        vizinhos2 = get_neighbords_color(n)
        #vizinhosN = get_neighbords(numbers[0], 1)
        #vizinhosN2 = get_neighbords_color(numbers[0])
        figuras = get_figure(soma_digitos(n))
        terminais = get_numbers_by_terminal(get_terminal(n))
        bet.extend([n, *mirror, *vizinhos, *vizinhos2, numbers[0] *figuras, *terminais, 0])

    bet = sorted({n for n in bet if isinstance(n, int) and 0 <= n <= 36})

    if not bet:
        return None

    classificador = ClassificadorProximidade(peso_principal = 4.5,
    peso_vizinhos = 1.4,
    peso_vizinhos1 = 1.2,
    peso_duzia = 0.5,
    peso_cor = 0,
    peso_puxada = 2,
    qtd_puxada = 10,
    decaimento = 0.5)

    for number in numbers[:100]:
        classificador.adicionar_numero(number)

    ranking = classificador.get_ranking()[:10]

    nums = [num for num, _ in ranking]

    matches = [n for n in nums if n in bet]

    return {
        "roulette_id": roulette["slug"],
        "roulette_name": roulette["name"],
        "roulette_url": roulette["url"],
        "pattern": "ALINHAMENTO",
        "triggers": [numbers[0]],  # zero mais recente
        "targets": [*bet],
        "bets": bet,
        "passed_spins": 0,
        "spins_required": 0,
        "spins_count": 0,
        "gales" : 1,
        "snapshot": numbers,
        "status": "processing",
        "score" : len(matches),
        "message": f"Gatilho ativado! base de números : {nums}",
        "tags": [],
    }



"""
Padrão: Cavalos Soma

Lógica:
1. Os dois últimos números devem pertencer ao mesmo grupo de cavalos (147, 258, 0369)
2. Os dois números NÃO podem ter o mesmo terminal (ex: 17 e 14 ok, mas 17 e 27 não)
3. Soma os dois números: 17 + 14 = 31
4. Pega o terminal da soma: 31 % 10 = 1
5. Aposta nos números com esse terminal + vizinhos de cilindro
6. Cancela se o número anterior à formação (posição 3) está na lista de aposta
"""

from helpers.utils.filters import get_terminal, get_numbers_by_terminal
from helpers.utils.get_neighbords import get_neighbords

import time


# Grupos de cavalos por terminal
CAVALOS = {
    "147": {1, 4, 7},  # Terminais 1, 4, 7
    "258": {2, 5, 8},  # Terminais 2, 5, 8
    "0369": {0, 3, 6, 9},  # Terminais 0, 3, 6, 9
}


def get_cavalo_group(num):
    """Retorna o grupo de cavalos ao qual o número pertence baseado no terminal."""
    terminal = get_terminal(num)
    for grupo, terminais in CAVALOS.items():
        if terminal in terminais:
            return grupo
    return None


def process_roulette(roulette, numbers):
    """
    Processa o padrão Cavalos Soma.

    Args:
        roulette: Dados da roleta
        numbers: Lista de números (mais recente no índice 0)

    Returns:
        dict com sinal ou None se não houver padrão
    """
    if len(numbers) < 3:
        return None

    # Pegar os dois últimos números
    num1 = numbers[0]  # Mais recente
    num2 = numbers[1]  # Anterior

    # Verificar se são iguais (não forma padrão)
    if num1 == num2:
        return None

    # Verificar se ambos pertencem ao mesmo grupo de cavalos
    grupo1 = get_cavalo_group(num1)
    grupo2 = get_cavalo_group(num2)

    if grupo1 is None or grupo2 is None:
        return None

    if grupo1 != grupo2:
        return None

    # Verificar se NÃO têm o mesmo terminal (condição obrigatória)
    terminal1 = get_terminal(num1)
    terminal2 = get_terminal(num2)

    if terminal1 == terminal2:
        return None

    # Somar os dois números
    soma = num1 + num2

    # Pegar o terminal da soma
    terminal_soma = get_terminal(soma)

    # Obter números com esse terminal
    numeros_terminal = get_numbers_by_terminal(terminal_soma)

    # Adicionar vizinhos de cilindro de cada número
    bet = set(numeros_terminal)
    for n in numeros_terminal:
        vizinhos = get_neighbords(n)
        bet.update(vizinhos)

    bet = sorted(bet)

    # Verificar cancelamento: se o número anterior (posição 2) está na lista
    if len(numbers) > 2:
        numero_anterior = numbers[2]
        if numero_anterior in bet:
            return None

    created_at = int(time.time())

    return {
        "roulette_id": roulette['slug'],
        "roulette_name": roulette["name"],
        "roulette_url": roulette["url"],
        "pattern": "CAVALOS_SOMA",
        "triggers": [num1, num2],
        "targets": [*bet],
        "bets": bet,
        "passed_spins": 0,
        "spins_required": 0,
        "spins_count": 0,
        "gales": 3,
        "score": 0,
        "snapshot": numbers[:200],
        "status": "processing",
        "message": f"Cavalos {grupo1}: {num1}+{num2}={soma} -> Terminal {terminal_soma}",
        "tags": [f"cavalo_{grupo1}", f"terminal_{terminal_soma}"],
        "temp_state": None,
        "created_at": created_at,
        "timestamp": created_at
    }

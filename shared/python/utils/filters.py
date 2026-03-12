from typing import Iterable, Tuple, Sequence, Optional, List

from helpers.utils.get_neighbords import (get_neighbords, get_neighbords_color)
from helpers.utils.get_mirror import get_mirror


from colorama import init, Fore, Back, Style
init(autoreset=True)


COLORS = {
    "red":    Fore.RED,
    "green":  Fore.GREEN,
    "yellow": Fore.YELLOW,
    "blue":   Fore.BLUE,
    "magenta" : Fore.MAGENTA,
    "cyan" : Fore.CYAN,
    "reset":  Style.RESET_ALL,
}


RED_NUMBERS = {
    1, 3, 5, 7, 9, 12, 14, 16, 18,
    19, 21, 23, 25, 27, 30, 32, 34, 36
}

BLACK_NUMBERS = {
    2, 4, 6, 8, 10, 11, 13, 15, 17,
    20, 22, 24, 26, 28, 29, 31, 33, 35
}


FIRST_DOZEN  = set(range(1, 13))   # 1 a 12
SECOND_DOZEN = set(range(13, 25))  # 13 a 24
THIRD_DOZEN  = set(range(25, 37))  # 25 a 36


def find_terminal(numero):
    return abs(numero) % 10


def sum_of_digits(number: int) -> int:
    return sum(int(d) for d in str(abs(number)))


def color_print(text: str, color: str = "reset") -> None:
    fmt = COLORS.get(color, COLORS["reset"])
    print(fmt + text)


def appears_in_slice(
    val: int,
    numbers: Sequence[int],
    start: int,
    end: int
) -> bool:
    
    return val in numbers[start:end]

def matches_index(
    numbers: Sequence[int],
    idx: int,
    val: int
) -> bool:
    return idx < len(numbers) and numbers[idx] == val


def first_index_after(
    numbers: Sequence[int],
    value: int,
    start: int
) -> Optional[int]:
    """
    Retorna o índice da primeira ocorrência de `value` em `numbers`
    começando em `start`. Se start >= len(numbers) ou não encontrar, retorna None.
    """

    # garante que não extrapolamos
    if start < 0:
        start = 0
    if start >= len(numbers):
        return None

    # itera exatamente do índice `start` até o fim
    for i in range(start, len(numbers)):
        if numbers[i] == value:
            return i

    return None

def is_check_neigbor_two_numbers(
        num1,
        num2
    ) :

    a = get_neighbords(num1)
    a.append(num1)


    if num2 in a : 
        return True

    return False


def is_valid_neighbor_confirmation(
    numbers: Sequence[int],
    first_idx: int,
    second_idx: int,
    neighbors: Sequence[int]
) -> bool:
    """
    Retorna True se o valor em numbers[second_idx+1]
    for igual a numbers[first_idx-1]  ou
    estiver em `neighbors`.
    """
    next_val = numbers[second_idx + 1]
    prev_val = numbers[first_idx  - 1]
    return next_val in (prev_val, *neighbors)



def is_consecutive(a: int, b: int) -> bool : 
    return abs(a - b) == 1

def is_skipped_sequence(a: int, b: int, skip: int = 2) -> bool:
    """
    Retorna True se a e b formarem uma sequência pulada
    (ex.: 12 e 14, ou 14 e 12), ou seja, |a - b| == skip.
    """
    return abs(a - b) == skip

def any_consecutive(val: int, others : Iterable[int]) -> bool : 
    return any(is_consecutive(val, o) for o in others) # Percorre o objeto others atrás de uma crescente ou decrescente

def has_consecutive_pair(numbers: Iterable[int], step: int = 1) -> bool: 
    return any(abs(b - a) == step for a, b in zip(numbers, numbers[1:]))

def has_adjacent_repetition(numbers:Iterable[int]) -> bool : 
    return any(a == b for a, b in zip(numbers, numbers[1:]))

def has_alternation(numbers: Iterable[int]) -> bool : 
    return any(a == b for a, b in zip(numbers, numbers[2:]))

def has_same_terminal(pairs: Iterable[Tuple[int, int]], base: int) -> bool:
    return any(
        a % 10 == base % 10 or b % 10 == base % 10
        for a, b in pairs
    )

def same_terminal(a: int, b: int) -> bool:
    return a % 10 == b % 10

def is_repetition(target: int, numbers) : 
    neighbords_target = get_neighbords(target)

    return (
        target in [numbers[0], numbers[3], numbers[4]] 
        or numbers[3] in neighbords_target
    )

def is_repetition_check(num1: int, num2: int) -> bool:
    """
    Retorna True se num2 for considerado repetição em relação a num1,
    usando qualquer uma das regras: mesmo número, vizinhos, vizinhos de cor ou espelhos.
    """
    # 1) Mesmo número
    if num1 == num2:
        return True

    # 2) Vizinhos diretos na roda
    if num2 in get_neighbords(num1):
        return True

    # 3) Vizinhos de cor (mesma cor, salto de índice 2 na roda)
    if num2 in get_neighbords_color(num1):
        return True

    # 4) Espelho
    if num2 in get_mirror(num1):
        return True


    # 5) Repetição de terminal (mesmo dígito final)
    if (num1 % 10) == (num2 % 10):
        return True
    return False

def find_relationship(a: int, b: int) -> Optional[List[str]]:

    relations: List[str] = []

    #Mesma cor na mesma duzia
    if ((a in RED_NUMBERS and b in RED_NUMBERS) or (a in BLACK_NUMBERS and b in BLACK_NUMBERS)) \
       and ((a in FIRST_DOZEN and b in FIRST_DOZEN) \
            or (a in SECOND_DOZEN and b in SECOND_DOZEN) \
            or (a in THIRD_DOZEN and b in THIRD_DOZEN)):
        relations.append("same_color_and_same_dozen")

    # mesmo terminal
    if find_terminal(a) == find_terminal(b):
        relations.append("same_terminal")

    # vizinhos
    if b in get_neighbords(a):
        relations.append("neighbors")

    # espelhos
    mirrors = get_mirror(a)
    if mirrors is not None:
        if isinstance(mirrors, list):
            if b in mirrors:
                relations.append("mirrors")
        else:
            if b == mirrors:
                relations.append("mirrors")

    # mesma soma de dígitos
    if sum_of_digits(a) == sum_of_digits(b):
        relations.append("same_digit_sum")

    return relations if relations else None

def confirmacao(aux,lista,number):
    primeira_confirmacao = None
    for i in range(aux, len(lista)):
        if lista[i] == number:
            primeira_confirmacao = i
            return primeira_confirmacao

    if primeira_confirmacao is None:
        return None

    if primeira_confirmacao + 1 >= len(lista):
        return None
    

def has_adjacent_terminal_repetition(numbers: list[int]) -> bool:
    for a, b in zip(numbers, numbers[1:]):
        if a % 10 == b % 10:
            return True
    return False

def get_numbers_by_terminal(terminal):
    """
    Retorna todos os números da roleta que terminam com o mesmo dígito do terminal
    
    Args:
        terminal (int): O número terminal (0-9)
    
    Returns:
        list: Lista com todos os números que terminam com o terminal
    """
    # Números da roleta europeia (0-36)
    roulette_numbers = list(range(0, 37))
    
    # Encontra todos os números que terminam com o mesmo dígito
    terminal_digit = terminal % 10
    numbers_with_terminal = []
    
    for number in roulette_numbers:
        if number % 10 == terminal_digit:
            numbers_with_terminal.append(number)
    
    return numbers_with_terminal

def get_terminal(num) :

    terminal = num % 10
    return terminal

def soma_digitos(numero):
    if numero == 29 : 
        return 2
    return sum(int(digito) for digito in str(numero))

def tem_consecutivos(lista1, lista2):
    return any(is_consecutive(num1, num2) 
               for num1 in lista1 
               for num2 in lista2)
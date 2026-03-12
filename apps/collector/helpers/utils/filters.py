from typing import Iterable, Tuple, Sequence, Optional

from helpers.utils.get_neighbords import get_neighbords

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

    #color_print(f"[Confirmando vizinhos ... {num1} com {num2}]", "green")

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

def any_consecutive(val: int, others : Iterable[int]) -> bool : 
    return any(is_consecutive(val, o) for o in others) 

def has_consecutive_pair(numbers: Iterable[int], step: int = 1) -> bool: 
    return any(abs(b - a) == step for a, b in zip(numbers, numbers[1:]))

def has_adjacent_repetition(numbers:Iterable[int]) -> bool : 
    return any(a == b for a, b in zip(numbers, numbers[1:]))

def has_alternation(numbers: Iterable[int]) -> bool : 
    return any(a == b for a, b in zip(numbers, numbers[2:]))

def has_same_terminal(pairs: Iterable[Tuple[int, int]], base : int = 10) -> bool : 
    return any(a % base == b % base  for a, b in pairs) 
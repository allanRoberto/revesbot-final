from helpers.utils.filters  import (
    is_consecutive,
)
from helpers.utils.get_neighbords import get_neighbords, get_neighbords_color
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



def process_roulette(roulette, numbers) :
    if(len(numbers) < 50) :
        return None
    
    # Dicionário para contar a frequência de cada terminal (0-9)
    terminal_count = {i: 0 for i in range(10)}

    p0 = numbers[0]
    p1 = numbers[1]
    p2 = numbers[2]

    if(is_consecutive(p0, p1)) :
        return None
    
    pt0 = get_terminal(p0)
    pt1 = get_terminal(p1)
    pt2 = get_terminal(p2)


    if(pt1 == pt2) :
        return None
    
    

    # Contar os terminais
    

  
    # Retornar apenas o terminal se houver exatamente 1
    if(pt0 == pt1) :

        terminals = get_numbers_by_terminal(pt0)

        bet = [*terminals]


        for terminal_number in terminals :
            neighbords = get_neighbords(terminal_number)
            neighbords_colors = get_neighbords_color(terminal_number)
            bet.extend(neighbords)
            bet.extend(neighbords_colors)
                

        bet.insert(0, 0)
        bet = sorted(set(bet))

        return {
                "roulette_id": roulette['slug'],
                "roulette_name" : roulette["name"],
                "roulette_url" : roulette["url"],
                "pattern" : "PREDOMINANCIA",
                "triggers":[numbers[0]],
                "targets":[*terminals],
                "bets":bet,
                "passed_spins" : 0,
                "spins_required" : 0,
                "spins_count": 0,
                "snapshot":numbers[:50],
                "status":"processing",
                "message" : "Gatilho encontrado!"
            }




    return None



    
     

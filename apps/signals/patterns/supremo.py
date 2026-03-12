from datetime import datetime
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


def process_roulette(roulette, numbers) :


    if (len(numbers) < 10) :
        return
    
    p0 = numbers[0]

    if 1 <= p0 <= 9 :
        after_trigger = p0

        if(after_trigger <= 3) :
            return None
        if after_trigger < len(numbers) :
            trigger = numbers[after_trigger]
            terminal = p0 % 10

            if trigger == numbers[after_trigger - 2] :
                return None
            
            if trigger == numbers[after_trigger + 2] :
                return None
            

            if trigger == 0 : 
                return None
            
            if numbers[after_trigger -1] == numbers[after_trigger + 1] :
                return None

            terminals = get_numbers_by_terminal(terminal)

            bet = [*terminals]

            for terminal_number in terminals :
                neighbords = get_neighbords(terminal_number)
                neighbord_colors = get_neighbords_color(terminal_number)
                bet.extend(neighbords)
                #bet.extend(neighbord_colors)

            bet.insert(0, 0)
            bet = sorted(set(bet))

            return {
                "roulette_id": roulette['slug'],
                "roulette_name" : roulette["name"],
                "roulette_url" : roulette["url"],
                "pattern" : "CONTAR_SPINS",
                "triggers":[trigger],
                "targets":[*terminals],
                "bets":bet,
                "passed_spins" : 0,
                "spins_required" : 0,
                "spins_count": 0,
                "snapshot":numbers[:50],
                "status":"waiting",
                "message" : "Gatilho encontrado!"
            }

            
           



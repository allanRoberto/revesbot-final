from helpers.utils.get_neighbords import get_neighbords, get_neighbords_color

def get_terminal(num) :

    terminal = num % 10
    return terminal


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

    if (len(numbers) < 50) : 
        return None
    
    pt0 = get_terminal(numbers[0])
    print(pt0, "pt0")
    if (pt0 == 4) :
        bets = [31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26, 0, 32, 15, 19, 4, 21,2,25,17]

        return {
                "roulette_id": roulette['slug'],
                "roulette_name" : roulette["name"],
                "roulette_url" : roulette["url"],
                "pattern" : "CONTAR_SPINS",
                "triggers":[numbers[0]],
                "targets":[12, 2, 22, 32],
                "bets":bets,
                "passed_spins" : 0,
                "spins_required" : 0,
                "spins_count": 0,
                "snapshot":numbers[:50],
                "status":"processing",
                "message" : "Gatilho encontrado!"
            }
    
    return None
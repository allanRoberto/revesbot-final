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
    
    print(len(numbers))
    if (len(numbers) < 90) :
       
        return None
    
    trigger = numbers[0]

    i1 = 0
    i2 = 30
    i3 = 60
    p10 = numbers[i1]
    p40 = numbers[i2]
    p70 = numbers[i3]
    
    pt10 = get_terminal(p10)
    pt40 = get_terminal(p40)
    pt70 = get_terminal(p70)

    print(p10, "p10")
    print(p40, "p40")
    print(p70, "p70")

    print(pt10, "pt10")
    print(pt40, "pt40")
    print(pt70, "pt70")

    if get_terminal(numbers[i3 + 1]) == pt70 or get_terminal(numbers[i3 - 1] == pt70): 
        return None
    
    if get_terminal(numbers[i2 + 1]) == pt40 or get_terminal(numbers[i2 - 1] == pt40): 
        return None


    if pt10 == pt40 and pt40 == pt70 : 

        terminals = get_numbers_by_terminal(p10)

        bet = [*terminals]

        for terminal_number in terminals :
            neighbords = get_neighbords(terminal_number)
            neighbord_colors = get_neighbords_color(terminal_number)
            bet.extend(neighbords)
            bet.extend(neighbord_colors)

        bet.insert(0, 0)
        bet = sorted(set(bet))

        return {
            "roulette_id": roulette['slug'],
            "roulette_name" : roulette["name"],
            "roulette_url" : roulette["url"],
            "pattern" : "CONTAR_10_40",
            "triggers":[trigger],
            "targets":[*terminals],
            "bets":bet,
            "passed_spins" : 0,
            "spins_required" : 0,
            "spins_count": 0,
            "snapshot":numbers[:90],
            "status":"waiting",
            "message" : "Gatilho encontrado!"
        }


    return None
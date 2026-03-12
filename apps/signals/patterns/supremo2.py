from helpers.utils.filters import first_index_after, get_neighbords, get_neighbords_color


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

    if(len(numbers) < 200) :
        print("len")
        return None
    
    p0 = numbers[0]
    p1 = numbers[1]
    p2 = numbers[2]
    p3 = numbers[3]
    p4 = numbers[4]
    p5 = numbers[5]


    if (p4 > 10) : 
        return None
    
    if (p5 < 17) : 
        return None
    
    mirror = [12, 21, 23, 32, 13, 31]

    check1 = first_index_after(numbers, p4, 5)
    check2 = numbers[check1+1]

    check3 = numbers[check1+1+check2+1]

    terminals_check = get_numbers_by_terminal(check3)


    bet_check = [*terminals_check]



    for terminal_number_check in terminals_check :
        neighbords_check = get_neighbords(terminal_number_check)
        bet_check.extend(neighbords_check)

    target = numbers[p5 + 1]


    if any(num in bet_check for num in [p0, p1, p2, p3]):
        print("JA PAGOU")
        return None

    if target in mirror : 
        return None
    
    terminals = get_numbers_by_terminal(target)

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
        "pattern" : "SUPREMO01",
        "triggers":[p4],
        "targets":[*terminals],
        "bets":bet,
        "passed_spins" : 0,
        "spins_required" : 0,
        "spins_count": 0,
        "snapshot":numbers[:200],
        "status":"waiting",
        "message" : f"Gatilho encontrado!"
    }

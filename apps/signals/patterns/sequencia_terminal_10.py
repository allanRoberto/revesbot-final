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

    if(len(numbers) < 10) :
        return None
    

    p0 = numbers[0]
    p10 = numbers[10]

    if(p0 == p10) :
        target = get_terminal(p10)

        if (target == 0 or target == 9) : 
            return None

        a = target + 1
        b = target - 1

        terminals_a = get_numbers_by_terminal(a)
        terminals_b = get_numbers_by_terminal(b)
        terminals_c = get_numbers_by_terminal(target)

        bet = [*terminals_a, *terminals_b, *terminals_c]

        bet.insert(0, 0)
        bet = sorted(set(bet))

        return {
            "roulette_id": roulette['slug'],
            "roulette_name" : roulette["name"],
            "roulette_url" : roulette["url"],
            "pattern" : "CONTAR_10_TERMINAL",
            "triggers":[numbers[0]],
            "targets":[a, b],
            "bets":bet,
            "passed_spins" : 0,
            "spins_required" : 0,
            "spins_count": 0,
            "snapshot":numbers[:90],
            "status":"processing",
            "message" : "Gatilho encontrado!"
        }


    return None
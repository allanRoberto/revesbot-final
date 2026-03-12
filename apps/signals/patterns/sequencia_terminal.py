from helpers.utils.get_neighbords import get_neighbords
from helpers.utils.get_mirror import get_mirror

from helpers.utils.filters import is_consecutive


def get_terminal(num) :

    terminal = num % 10
    return terminal

def soma_digitos(numero):
    return sum(int(digito) for digito in str(numero))

def tem_consecutivos(lista1, lista2):
    return any(is_consecutive(num1, num2) 
               for num1 in lista1 
               for num2 in lista2)


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
    if(len(numbers) < 50) :
        return None
    
    idxs = (0, 1, 2, 3, 4, 5, 6)

    p0, p1, p2, p3 ,p4, p5, p6 = [numbers[i] for i in idxs]

    pt0 = get_terminal(p0)
    pt1 = get_terminal(p1)
    pt2 = get_terminal(p2)
    pt3 = get_terminal(p3)
    pt4 = get_terminal(p4)
    pt5 = get_terminal(p5)
    pt6 = get_terminal(p6)

    pm3 = get_mirror(p3)
    pm0 = get_mirror(p0)

    if (p3 > 9) :
        soma_p3 = soma_digitos(p3)

        if(soma_p3 == p0) :
            return None

    if (p1 > 9) :
         soma_p1 = soma_digitos(p2)

         if (soma_p1 * 2 == p0) :
             return None

    if(tem_consecutivos(pm0, pm3)) : 
        return None
    
    if p4 in pm3 :
        return None
    
    if p3 in pm0 :
        return None

    if p3 == 0 :
        return None
    
    if p3 == 33 and p2 == 30 :
        return None
    
    if p3 == 22 and p2 == 20 :
        return None
    
    if p3 == p0 :
        return None
    
    if p0 == 0 :
        return None
    
    if pt3 == pt2 :
        return None
    
    if (is_consecutive(p0, p1)) :
        return None

    if (is_consecutive(pt0, pt1)) :
        return None
    
    if (is_consecutive(pt2, pt3)) :
        return None



    if p1 == p2 and p1 != p0 and p2 != p3 and p3 != p4 and pt3 != pt4 and p3 != p1:

        

        pt1 = get_terminal(p1)

        terminals = get_numbers_by_terminal(pt1)

        bet = [*terminals]

        for terminal_number in terminals :
            neighbords = get_neighbords(terminal_number)
            bet.extend(neighbords)
        

        bet.insert(0, 0)
        bet = sorted(set(bet))
        
        trigger = p3
        target = p0

    
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
    
    return None
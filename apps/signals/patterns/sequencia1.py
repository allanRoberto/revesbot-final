from helpers.utils.filters import (
    is_consecutive
)
def get_terminal(num) :

    terminal = num % 10
    return terminal

def soma_digitos(numero) :
    if 10 <= numero <= 99:
        soma = int(str(numero)[0]) + int(str(numero)[1])
        return soma
    else:
       return numero

from helpers.utils.get_neighbords import get_neighbords, get_neighbords_color
from helpers.utils.get_mirror import get_mirror

def process_roulette(roulette, numbers) :
    
    idxs = (0, 1, 2, 3, 4, 5)

    p0, p1, p2, p3, p4, p5 = [numbers[i] for i in idxs]

    if(is_consecutive(p1, p2)) :

        target = p3

        target2 = p4

        trigger = p0

        trigger_neighbords = get_neighbords(trigger)

        target_neighbords = get_neighbords(target)
        p2_neighbords = get_neighbords(p2)
        p4_neighbords = get_neighbords(p4)
        p5_neighbords = get_neighbords(p5)

        trigger_mirror = get_mirror(trigger)
        target_mirror = get_mirror(target)
        p1_mirror = get_mirror(p1)
        p4_mirror = get_mirror(p4)


        trigger_terminal = get_terminal(trigger)
        p1_terminal = get_terminal(p1)

        target_terminal = get_terminal(target)
        p2_terminal = get_terminal(p2)

        if(is_consecutive(target_terminal, p2_terminal)) :
            return None


        soma_target = soma_digitos(target);
        soma_trigger = soma_digitos(trigger);
        
        soma_p0 = soma_digitos(p0)
        soma_p1 = soma_digitos(p1)
        soma_p2 = soma_digitos(p2)
        soma_p4 = soma_digitos(p4)

        if(target in p2_neighbords) :
            return None

        p0_terminal = get_terminal(p0)

        if(soma_p1 == trigger) :
            return None

        if any(is_consecutive(num1, soma_p0) for num1 in [p1, p2]) :
            return None
        
        if p4 in p5_neighbords :
            return None


        if(p1 in target_mirror) :
            return None

        if(soma_p2 == soma_target) : 
            return None
        
        if(soma_p4 == soma_target) : 
            return None

        if(p2_terminal == target_terminal) :
            return None
        
        if(trigger_mirror == target_mirror) :
            return None
        
        if p0 == p4 : 
            return None

        if p1 == 0 or p2 == 0 or p0 == 0: 
            return None

        if target == 0 or target2 == 0 :
            return None
        


        


        if (target == 11 and trigger == 33 or 
            target == 11 and trigger == 22 or 
            target == 22 and trigger == 11 or
            target == 22 and trigger == 33 or
            target == 33 and trigger == 22 or
            target == 33 and trigger == 11) :
            
            return None
        
        if target in trigger_mirror :
            return None

        if p2 == p4 : 
            return None

        if soma_target == soma_trigger :
            return None
        
        if(is_consecutive(soma_target, soma_trigger)) :
            return None 
        
        if(is_consecutive(soma_target, trigger)) :
            return None
        
        if (is_consecutive(p0, p4)) :
            return None

        if is_consecutive(p2, p4) :
            return None


        if any(is_consecutive(num1, target) for num1 in trigger_mirror) :
            return None
        
        if any(is_consecutive(num1, p0) for num1 in [soma_p1, soma_p2]) :
            return None
        
        if any(is_consecutive(num1, num2) 
               for num1 in target_mirror 
               for num2 in p4_mirror) :
            return None
        
        if any(is_consecutive(num1, target) for num1 in [p1, p2]) :
            return None
        
        if any(is_consecutive(num1, trigger) for num1 in p1_mirror) :
            return None
        
        if any(is_consecutive(num1, trigger_terminal) for num1 in [p1_terminal, p2_terminal]) :
            return None
        
        if any(is_consecutive(num1, trigger) for num1 in target_mirror) :
            return None
        
        if any(is_consecutive(num1, p1) for num1 in trigger_mirror) :
            return None
        
        if any(is_consecutive(num1, p3) for num1 in target_mirror) :
            return None

        if(target == trigger) :
            return None
        
        if(target in trigger_neighbords  or trigger in target_neighbords) :
            return None
        
        if p4 == 0 :
            return None
        
        if p4 == p3 : 
            return None

        if p3 == p2 : 
            return None
        
        if p0 == p1 :
            return None
        

        if(is_consecutive(p4, p3)) :
            return None


        target_neighbords = get_neighbords(p3)
        target_color_neighbords = get_neighbords_color(p3)
        target2_neighbords = get_neighbords(p4)
        target2_color_neighbords = get_neighbords_color(p4)

        bet = [target, target2, *target_neighbords, *target2_neighbords]  

        mirror_list = [m for n in bet for m in get_mirror(n)]

        bet.extend(mirror_list)

        bet.insert(0, 0)

        bet = sorted(set(bet))
        
        return {
          "roulette_id": roulette['slug'],
          "roulette_name" : roulette["name"],
          "roulette_url" : roulette["url"],
          "pattern" : "SEQUENCIA PULADA",
          "triggers":[trigger],
          "targets":[p3],
          "bets":bet,
          "passed_spins" : 0,
          "spins_required" : 0,
          "spins_count": 0,
          "snapshot":numbers[:50],
          "status":"waiting",
          "message" : "Gatilho encontrado!"
     }
    
    return None
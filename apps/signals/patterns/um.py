from helpers.utils.filters import is_consecutive, get_mirror, get_neighbords, soma_digitos
from helpers.utils.get_figure import get_figure


def process_roulette(roulette, numbers) : 

    target = numbers[0]
    trigger_base = numbers[1]
    triggers = []
    mirror_list = [m for n in [trigger_base, trigger_base + 1, trigger_base -1] for m in get_mirror(n)]

    vizinhos = get_neighbords(trigger_base)
    vizinhos_target = get_neighbords(target)
    vizinhos_n2 = get_neighbords(numbers[2])
    vizinhos_n3 = get_neighbords(numbers[3])

    figure_target = get_figure(soma_digitos(target))
    figure_n1 = get_figure(soma_digitos(numbers[1]))
    figure_n2 = get_figure(soma_digitos(numbers[2]))
    figure_n3 = get_figure(soma_digitos(numbers[3]))

    espelhos_n1 = get_mirror(numbers[1])


    if(is_consecutive(soma_digitos(target), soma_digitos(numbers[1]))) :
        return None



    for espelho_n1 in espelhos_n1 :
        if(is_consecutive(espelho_n1, numbers[2])) :
            return None
    

    #triggers.extend(mirror_list)

    espelhos_target = get_mirror(target)

    triggers.insert(0, trigger_base)
    triggers.insert(0, trigger_base+1)
    triggers.insert(0, trigger_base-1)

    triggers = sorted(set(triggers)) 

    for vizinho_n2 in vizinhos_n2 :
        if(is_consecutive(vizinho_n2, trigger_base)) :
            return None

    for vizinho_n2 in vizinhos_n2 :
        for vizinho_n3 in vizinhos_n3 :
            if(vizinho_n2 == vizinho_n3) :
                return None
    
    for vizinho in vizinhos :
        for vizinho_target in vizinhos_target :
            if(is_consecutive(vizinho, vizinho_target)) :
                return None


    for espelho_target in espelhos_target :
        if(is_consecutive(espelho_target, trigger_base)) :
            return None
    if (target in vizinhos) :
        return None
    
    if (numbers[1] == numbers[2]):
        return None
    
    for vizinho in vizinhos :
        if is_consecutive(vizinho, target) :
            return None
        
    for vizinho in vizinhos :
        if is_consecutive(vizinho, numbers[2]) :
            return None


    if numbers[2] in vizinhos_target :
        return None    
    
    if numbers[1] in vizinhos_n2 :
        return None    
    
    if is_consecutive(numbers[1], numbers[3]) :
        return None
    
    if numbers[1] == numbers[3] :
        return None

    for vizinho_target in vizinhos_target :
        if is_consecutive(vizinho_target, numbers[2]) :
            return None
        
    for vizinho_n2 in vizinhos_n2 :
        for vizinho in vizinhos :
            if(is_consecutive(vizinho, vizinho_n2)) :
                return None
    
    if is_consecutive(numbers[1], numbers[2]) :
        return None

    if(numbers[0] == numbers[1]) :
        return None
    
    if is_consecutive(target, trigger_base) :
        return None
    
    if is_consecutive(numbers[0], numbers[1]) :
        return None
    
    bet = [target]

    vizinhos1 = get_neighbords(target, 1)
    vizinhos2 = get_neighbords(target, 2)
    vizinhos3 = get_neighbords(target, 3)
    vizinhos4 = get_neighbords(target, 4)
    vizinhos5 = get_neighbords(target, 5)
    vizinhos6 = get_neighbords(target, 6)


    bet = sorted(set(bet))

    bet.extend(espelhos_target)
    return {
                "roulette_id": roulette['slug'],
                "roulette_name" : roulette["name"],
                "roulette_url" : roulette["url"],
                "pattern" : "UM_NUMERO",
                "triggers":triggers,
                "targets":[target, *espelhos_target],
                "bets": bet,
                "passed_spins" : 0,
                "spins_required" : 3,
                "spins_count": 0,
                "gales" : 1,
                "score" : 0,
                "snapshot":numbers[:50],
                "status": "processing",
                "message" : "Gatilho encontrado!",
                "tags" : [],
            }
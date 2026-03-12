from helpers.utils.filters import first_index_after, is_consecutive

from helpers.utils.get_neighbords import get_neighbords

from helpers.utils.get_mirror import get_mirror

def process_roulette(roulette, numbers) :

    if len(numbers) < 50 :
        print('Números insuficientes')
        return None

    p8 = numbers[8]

    print(p8)

    if p8 in numbers[0:7] :
        print('Pagou o gatilho antes de 10 rodadas...')
        return None

    indice1 = first_index_after(numbers, p8, 9)

    if indice1 is None :
        print('Indice 1 não encontrado')
        return None

    indice2 = first_index_after(numbers, p8, indice1 + 1)

    if indice2 is None :
        print('Indice 2 não encontrado')
        return None
    
  
    
    if indice2 > 200 :
        print(f'Indice 2 maior que 200, {indice2} - {p8}')
        return None

    alvo = numbers[indice2+1]

    if alvo == 0 :
        print('Alvo é igual ZERO')
        return None
    
    
    
    
    
    if indice1 < 10 :
        print('Indice 1 menor que 10')
        #return None

    if alvo in numbers[9:15] :
        print(f'Alvo pago entre 9 e 15 rodadas')
        #return None
    
    if alvo in numbers[0:7] :
        print('Alvo pago entre 0 e 7 rodadas')
        return None
    
    if is_consecutive(alvo, numbers[7]) :
        print('Alvo tá vindo de uma sequencia')
        return None
    
    
    vizinhos_alvo = get_neighbords(alvo)
    espelho_alvo = get_mirror(alvo)



    bet = [*vizinhos_alvo, *espelho_alvo, alvo]

    mirror_list = [m for n in bet for m in get_mirror(n)]

    bet.extend(mirror_list)

    bet.insert(0, p8)

    bet = sorted(set(bet))


    pagou = any(num in bet for num in numbers[0:7]) 

    pagou = False

    if pagou :
        print('Pagou entre 0 e 7 posicoes')
        #return None 
    
    if len(bet) > 6 :
        print('Aposta maior que  6')
        #return None
    

    return {
        "roulette_id": roulette["slug"],
        "roulette_name": roulette["name"],
        "roulette_url": roulette["url"],
        "pattern": "ALINHAMENTO-FINAL",
        "triggers": [numbers[8]],  # zero mais recente
        "targets": [*bet],
        "bets": bet,
        "passed_spins": 0,
        "spins_required": 0,
        "spins_count": 0,
        "snapshot": numbers,
        "status": "processing",
        "gales" : 6,
        "message": f"Gatilho ativado! base de números : {alvo}",
        "tags": [],
    }

    


from helpers.utils.filters import (
    is_skipped_sequence,
    soma_digitos,
    get_terminal,
    is_consecutive
)

from helpers.utils.get_figure import get_figure



from filters.run_all_filters import run_all_filters



debug = True


# Função auxiliar para determinar a dúzia de um número
def obter_duzia(numero):
    if 1 <= numero <= 12:
        return 1
    elif 13 <= numero <= 24:
        return 2
    elif 25 <= numero <= 36:
        return 3
    else:
        return None  # Número fora do range válido

def verificar_duzia(num1, num2):
    """
    Verifica qual dúzia dois números pertencem.
    
    Dúzias:
    - Primeira dúzia: 1-12
    - Segunda dúzia: 13-24  
    - Terceira dúzia: 25-36
    
    Args:
        num1: Primeiro número
        num2: Segundo número
    
    Returns:
        int: Número da dúzia (1, 2 ou 3) se ambos números estão na mesma dúzia
        None: Se os números estão em dúzias diferentes ou se algum número é 0
    """
    
    # Se algum número for 0, retorna None
    if num1 == 0 or num2 == 0:
        return None
    
    # Obtém as dúzias dos dois números
    duzia1 = obter_duzia(num1)
    duzia2 = obter_duzia(num2)
    
    # Se algum número está fora do range válido, retorna None
    if duzia1 is None or duzia2 is None:
        return None
    
    # Se as dúzias são diferentes, retorna None
    if duzia1 != duzia2:
        return None
    
    # Se chegou aqui, ambos números estão na mesma dúzia
    return duzia1

def process_roulette(roulette, numbers) : 

    if len(numbers) < 10 :
        return None
    

    idxs = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9)
    p0, p1, p2, p3, p4, p5, p6, p7, p8, p9 = [numbers[i] for i in idxs] 

    pos1 = p1
    pos2 = p2
    target = p3 #Alvo para formação da aposta
    check1 = p4 #Sequência
    check2 = p5 #Sequência
    trigger = p6 #Gatilho
    pos7 = p7
    pos8 = p8
 
    if trigger in numbers[0:5] :
        return None

    # Pré-condição da lógica original
    if not is_consecutive(check1, check2):
          return None  


    bloqueado, tags = run_all_filters(numbers)

    # Por enquanto não bloqueia, apenas coleta tags
    bloqueado = False

    if(bloqueado) : 
        return None
    
    
    duzia = verificar_duzia(check1, check2)

    if duzia == None :
        return None

    duzia_gatilho = obter_duzia(trigger)

    soma_trigger = soma_digitos(trigger);

    if soma_trigger >= 10 :
        return None

    elif soma_trigger == 9 :
        soma_trigger1 = 8
        soma_trigger2 = 1
        soma_trigger3 = 7
        soma_trigger4 = 2
    

    elif soma_trigger == 8 :
        soma_trigger1 = 7
        soma_trigger2 = 9
        soma_trigger3 = 6
        soma_trigger4 = 1

    elif soma_trigger == 7 :
        soma_trigger1 = 6
        soma_trigger2 = 8
        soma_trigger3 = 5
        soma_trigger4 = 9

    elif soma_trigger == 6 :
        soma_trigger1 = 5
        soma_trigger2 = 7
        soma_trigger3 = 4
        soma_trigger4 = 8

    elif soma_trigger == 5 :
        soma_trigger1 = 4
        soma_trigger2 = 6
        soma_trigger3 = 3
        soma_trigger4 = 7
    
    elif soma_trigger == 4 :
        soma_trigger1 = 3
        soma_trigger2 = 5
        soma_trigger3 = 2
        soma_trigger4 = 6
    
    elif soma_trigger == 3 :
        soma_trigger1 = 2
        soma_trigger2 = 4
        soma_trigger3 = 1
        soma_trigger4 = 5

    elif soma_trigger == 2 :
        soma_trigger1 = 1
        soma_trigger2 = 3
        soma_trigger3 = 9
        soma_trigger4 = 4
    
    if soma_trigger == 1 :
        soma_trigger1 = 9
        soma_trigger2 = 2
        soma_trigger3 = 8
        soma_trigger4 = 3
    



    figure_trigger = get_figure(soma_trigger)
    figure_trigger1 = get_figure(soma_trigger1)
    figure_trigger2 = get_figure(soma_trigger2)
    figure_trigger3 = get_figure(soma_trigger3)
    figure_trigger4 = get_figure(soma_trigger4)

    bets = [*figure_trigger, *figure_trigger1, *figure_trigger2]


    if duzia != duzia_gatilho :
        if duzia == 1:
            bet = [num for num in bets if 1 <= num <= 12]
        elif duzia == 2:
            bet = [num for num in bets if 13 <= num <= 24]
        elif duzia == 3:
            bet = [num for num in bets if 25 <= num <= 36]

    
        bet.insert(0, 0)

        
        return {
            "roulette_id": roulette['slug'],
            "roulette_name" : roulette["name"],
            "roulette_url" : roulette["url"],
            "pattern" : "SEQUENCIA",
            "triggers":[trigger],
            "targets":[p4, p5],
            "bets":bet,
            "passed_spins" : 0,
            "spins_required" : 0,
            "spins_count": 0,
            "snapshot":numbers[:50],
            "status":"waiting",
            "message": "Gatilho encontrado!",
            "tags": tags,  # Adicionando as tags coletadas
    }
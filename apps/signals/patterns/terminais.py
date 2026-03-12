from helpers.utils.get_neighbords import get_neighbords
from helpers.utils.get_mirror import get_mirror
from collections import Counter
from typing import List, Set

from typing import List, Dict, Callable, Tuple


from helpers.utils.filters import (
    is_consecutive,
    any_consecutive,
    same_terminal,
    is_repetition_check
)

def existe_consecutivo_entre_tres(numeros: List[int]) -> bool:
    for i in range(len(numeros)):
        val = numeros[i]
        others = [n for j, n in enumerate(numeros) if j != i]
        if any_consecutive(val, others):
            return True
    return False

def montar_base_com_vizinhos(terminal: int) -> List[int]:
    # Números com o terminal desejado
    base = [n for n in range(37) if n % 10 == terminal]


    resultado: Set[int] = set(base)

    # Adiciona os vizinhos de cada número
    for numero in base:
        vizinhos = get_neighbords(numero)
        resultado.update(vizinhos)

    return sorted(resultado)

def is_consecutive_terminal(a: int, b: int) -> bool:
    ta = a % 10
    tb = b % 10
    return ta != tb and (tb > ta or tb < ta)

DEBUG=True

FILTER_SWITCHES: Dict[str, bool] = {
    "consecutive": True,      # is_consecutive / any_consecutive
    "same_terminal": True,      # is_consecutive / any_consecutive
    "alternancia": True,      # is_consecutive / any_consecutive
    "repetition": True,      # is_consecutive / any_consecutive
    "paid": True,      # is_consecutive / any_consecutive
}

def _log(cat: str, name: str) -> None:
    """Mostra qual filtro bloqueou quando DEBUG = True"""
    if DEBUG:
        print(f"[FILTRO] ({cat}) → {name}")

Filter = Tuple[str, str, Callable[[], bool]]  # (categoria, nome, condição)


def process_roulette(roulette, numbers) :

    
    idxs = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9)
    p0, p1, p2, p3, p4, p5, p6, p7, p8, p9 = [numbers[i] for i in idxs] 

    pos0 = p0
    trigger = p1
    pos2 = p2
    pos3 = p3

    filters : List[Filter] = []

    #FILTROS DO GATILHO
    if FILTER_SWITCHES["consecutive"] :
        filters += [
            ("consecutive", "SEQUENCIA COM GATILHO E NÚMERO ANTERIOR DETECTADA", lambda : is_consecutive(trigger, pos2)),
            ("consecutive", "SEQUENCIA COM GATILHO E PRÓXIMO NÚMERO DETECTADA", lambda : is_consecutive(trigger, pos0)),
            ("consecutive", "SEQUENCIA ANTES DO GATILHO",    lambda : is_consecutive(pos2, pos3)),
        ]
    
    if FILTER_SWITCHES["same_terminal"] :
        filters += [
            ("same_terminal", "REPETICAO DE TERMINAIS COM GATILHO DETECTADA", lambda : same_terminal(trigger, pos2)),
            ("consecutive", "REPETICAO DE TERMINAL POS GATILHO", lambda : same_terminal(trigger, pos0)),
            ("consecutive", "REPETICAO DE TERMINAL ANTES DO GATILHO",    lambda : same_terminal(pos2, pos3)),
        ]
    
    if FILTER_SWITCHES["alternancia"] :
        filters += [
            ("same_terminal", "ALTERNANCIA COM GATILHO DETECTADA", lambda : pos0 == pos2),
        ]

    # guarda mínima: precisamos de pelo menos 3 números para olhar i+2
    if len(numbers) < 3:
        print("MENOR")
        return None

    # reserve 2 posições de look-ahead no recorte para não estourar i+2
    limite = min(250, len(numbers) - 2)

    # índices do trigger dentro do recorte, garantindo que i-1 é válido
    indices = [i for i, v in enumerate(numbers[:limite]) if v == trigger and i >= 1]

    # você usa a 2ª, 3ª e 4ª ocorrências
    if len(indices) < 4:
        print("INDICE", indices)
        return None

    i1, i2, i3 = indices[1:4]

    # agora i+2 é seguro porque limite <= len(numbers) - 2
    antes_alvo_1 = numbers[i1 + 2]
    antes_alvo_2 = numbers[i2 + 2]
    antes_alvo_3 = numbers[i3 + 2]

    mirror_antes_alvo_1 = get_mirror(antes_alvo_1)
    mirror_antes_alvo_2 = get_mirror(antes_alvo_2)
    mirror_antes_alvo_3 = get_mirror(antes_alvo_3)

    alvo1 = numbers[i1 - 1]  # seguro porque filtramos i >= 1
    alvo2 = numbers[i2 - 1]
    alvo3 = numbers[i3 - 1]

    mirror_alvo1 = get_mirror(alvo1)
    mirror_alvo2 = get_mirror(alvo2)
    mirror_alvo3 = get_mirror(alvo3)
        
    
    if FILTER_SWITCHES["repetition"] :
        filters += [
            ("repetition", "REPETICAO COM ALVO 1", lambda : antes_alvo_1 == alvo1),
            ("repetition", "REPETICAO COM ALVO 2", lambda : antes_alvo_2 == alvo2),
            ("repetition", "REPETICAO COM ALVO 3", lambda : antes_alvo_3 == alvo3),
            ("repetition", "REPETICAO COM ALVO 1 com espelho", lambda : antes_alvo_1 in mirror_antes_alvo_1),
            ("repetition", "REPETICAO COM ALVO 2 com espelho", lambda : antes_alvo_2 in mirror_antes_alvo_2),
            ("repetition", "REPETICAO COM ALVO 3 com espelho", lambda : antes_alvo_3 in mirror_antes_alvo_3),
            ("repetition", "REPETICAO COM ALVO 1 com GATILHO", lambda : alvo1 == trigger),
            ("repetition", "REPETICAO COM ALVO 2 com GATILHO", lambda : alvo2 == trigger),
            ("repetition", "REPETICAO COM ALVO 3 com GATILHO", lambda : alvo3 == trigger),
            ("repetition", "REPETICAO COM ESPELHO ALVO 1 com GATILHO", lambda : trigger in mirror_alvo1),
            ("repetition", "REPETICAO COM ESPELHO ALVO 2 com GATILHO", lambda : trigger in mirror_alvo2),
            ("repetition", "REPETICAO COM ESPELHO ALVO 3 com GATILHO", lambda : trigger in mirror_alvo3),
        ]

    if FILTER_SWITCHES["consecutive"] :
        filters += [
            ("consecutive", "SEQUENCIA COM GATILHO E ALVO 1", lambda : is_consecutive(trigger, alvo1)),
            ("consecutive", "SEQUENCIA COM GATILHO E ALVO 2", lambda : is_consecutive(trigger, alvo2)),
            ("consecutive", "SEQUENCIA COM GATILHO E ALVO 3", lambda : is_consecutive(trigger, alvo3)),            
        ]

    
        

    alvo1_neighbords = get_neighbords(alvo1)
    alvo2_neighbords = get_neighbords(alvo2)
    alvo3_neighbords = get_neighbords(alvo3)
    alvo4_neighbords = get_neighbords(p0)

    all_neighbords = alvo1_neighbords + alvo2_neighbords + alvo3_neighbords + alvo4_neighbords

    terminais = [n % 10 for n in all_neighbords]

    contagem = Counter(terminais)

    # Filtra apenas os que apareceram pelo menos 2 vezes
    filtrados = [(k, v) for k, v in contagem.items() if v >= 2]
    if not filtrados:
        print(filtrados, "filtrados")
        return None

    # Ordena por frequência decrescente
    ordenados = sorted(filtrados, key=lambda x: -x[1])

    # Pega os dois primeiros (ou só um, se houver só um)
    top_terminais = [t[0] for t in ordenados[:2]]


    if(len(top_terminais) > 1) :
        return None  

    aposta = montar_base_com_vizinhos(top_terminais[0])


    if(top_terminais[0] == 1) :
        aposta.insert(0, 10)
    
    if(top_terminais[0] == 2) :
        aposta.insert(0, 20)
        aposta.insert(0, 22)

    if(top_terminais[0] == 3) :
        aposta.insert(0, 30)
        aposta.insert(0, 33)

    aposta.insert(0, 0)
    aposta.insert(0, alvo1)
    aposta.insert(0, alvo2)
    aposta.insert(0, alvo3)

    

    aposta = sorted(set(aposta))

    if FILTER_SWITCHES["paid"] :
        filters += [
            ("paid", "APOSTA PAGA IMEDIATAMENTE", lambda : pos0 in aposta),
            ("paid", "GATILHO SUSPEITO", lambda : trigger in (33, 28, 13, 17, 4, 5, 3, 20, 10, 7, 25, 8,)),           
        ]
    
    return {
            "roulette_id": roulette['slug'],
            "roulette_name" : roulette["name"],
            "roulette_url" : roulette["url"],
            "pattern" : "TERMINAL",
            "triggers":[trigger],
            "targets":[alvo1, alvo2, alvo3, top_terminais[0]],
            "bets":aposta,
            "passed_spins" : 0,
            "spins_required" : 3,
            "spins_count": 5,
            "snapshot":numbers[:150],
            "status":"pending",
            "message": "Gatilho identificado"
    }
    


    
    
    

    
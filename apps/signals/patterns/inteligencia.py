import requests
import asyncio
import os
import re
from collections import defaultdict, Counter
from itertools import combinations
import time
from datetime import datetime
from core.api import RouletteAPI
from dotenv import load_dotenv

ROULETTE_WHEEL_ORDER = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26]

NUMEROS_ROLETA = {
    0: {'cor': 'verde', 'duzia': None, 'coluna': None, 'par_impar': None, 'alto_baixo': None, 'terminal': 0, 'voisins': False, 'orphelins': False, 'tiers': False},
    1: {'cor': 'vermelho', 'duzia': 1, 'coluna': 1, 'par_impar': 'impar', 'alto_baixo': 'baixo', 'terminal': 1, 'voisins': False, 'orphelins': True, 'tiers': False},
    2: {'cor': 'preto', 'duzia': 1, 'coluna': 2, 'par_impar': 'par', 'alto_baixo': 'baixo', 'terminal': 2, 'voisins': False, 'orphelins': False, 'tiers': True},
    3: {'cor': 'vermelho', 'duzia': 1, 'coluna': 3, 'par_impar': 'impar', 'alto_baixo': 'baixo', 'terminal': 3, 'voisins': True, 'orphelins': False, 'tiers': False},
    4: {'cor': 'preto', 'duzia': 1, 'coluna': 1, 'par_impar': 'par', 'alto_baixo': 'baixo', 'terminal': 4, 'voisins': True, 'orphelins': False, 'tiers': False},
    5: {'cor': 'vermelho', 'duzia': 1, 'coluna': 2, 'par_impar': 'impar', 'alto_baixo': 'baixo', 'terminal': 5, 'voisins': False, 'orphelins': True, 'tiers': False},
    6: {'cor': 'preto', 'duzia': 1, 'coluna': 3, 'par_impar': 'par', 'alto_baixo': 'baixo', 'terminal': 6, 'voisins': True, 'orphelins': False, 'tiers': False},
    7: {'cor': 'vermelho', 'duzia': 1, 'coluna': 1, 'par_impar': 'impar', 'alto_baixo': 'baixo', 'terminal': 7, 'voisins': True, 'orphelins': False, 'tiers': False},
    8: {'cor': 'preto', 'duzia': 1, 'coluna': 2, 'par_impar': 'par', 'alto_baixo': 'baixo', 'terminal': 8, 'voisins': True, 'orphelins': True, 'tiers': False},
    9: {'cor': 'vermelho', 'duzia': 1, 'coluna': 3, 'par_impar': 'impar', 'alto_baixo': 'baixo', 'terminal': 9, 'voisins': False, 'orphelins': False, 'tiers': False},
    10: {'cor': 'preto', 'duzia': 1, 'coluna': 1, 'par_impar': 'par', 'alto_baixo': 'baixo', 'terminal': 0, 'voisins': False, 'orphelins': True, 'tiers': False},
    11: {'cor': 'preto', 'duzia': 2, 'coluna': 2, 'par_impar': 'impar', 'alto_baixo': 'baixo', 'terminal': 1, 'voisins': False, 'orphelins': False, 'tiers': True},
    12: {'cor': 'vermelho', 'duzia': 1, 'coluna': 3, 'par_impar': 'par', 'alto_baixo': 'baixo', 'terminal': 2, 'voisins': True, 'orphelins': False, 'tiers': False},
    13: {'cor': 'preto', 'duzia': 2, 'coluna': 1, 'par_impar': 'impar', 'alto_baixo': 'baixo', 'terminal': 3, 'voisins': False, 'orphelins': False, 'tiers': True},
    14: {'cor': 'vermelho', 'duzia': 2, 'coluna': 2, 'par_impar': 'par', 'alto_baixo': 'baixo', 'terminal': 4, 'voisins': False, 'orphelins': True, 'tiers': False},
    15: {'cor': 'preto', 'duzia': 2, 'coluna': 3, 'par_impar': 'impar', 'alto_baixo': 'baixo', 'terminal': 5, 'voisins': True, 'orphelins': False, 'tiers': False},
    16: {'cor': 'vermelho', 'duzia': 2, 'coluna': 1, 'par_impar': 'par', 'alto_baixo': 'baixo', 'terminal': 6, 'voisins': False, 'orphelins': False, 'tiers': True},
    17: {'cor': 'preto', 'duzia': 2, 'coluna': 2, 'par_impar': 'impar', 'alto_baixo': 'baixo', 'terminal': 7, 'voisins': True, 'orphelins': True, 'tiers': False},
    18: {'cor': 'vermelho', 'duzia': 2, 'coluna': 3, 'par_impar': 'par', 'alto_baixo': 'baixo', 'terminal': 8, 'voisins': False, 'orphelins': True, 'tiers': False},
    19: {'cor': 'vermelho', 'duzia': 2, 'coluna': 1, 'par_impar': 'impar', 'alto_baixo': 'alto', 'terminal': 9, 'voisins': False, 'orphelins': False, 'tiers': True},
    20: {'cor': 'preto', 'duzia': 2, 'coluna': 2, 'par_impar': 'par', 'alto_baixo': 'alto', 'terminal': 0, 'voisins': True, 'orphelins': False, 'tiers': False},
    21: {'cor': 'vermelho', 'duzia': 2, 'coluna': 3, 'par_impar': 'impar', 'alto_baixo': 'alto', 'terminal': 1, 'voisins': True, 'orphelins': False, 'tiers': True},
    22: {'cor': 'preto', 'duzia': 3, 'coluna': 1, 'par_impar': 'par', 'alto_baixo': 'alto', 'terminal': 2, 'voisins': False, 'orphelins': False, 'tiers': True},
    23: {'cor': 'vermelho', 'duzia': 3, 'coluna': 2, 'par_impar': 'impar', 'alto_baixo': 'alto', 'terminal': 3, 'voisins': False, 'orphelins': True, 'tiers': False},
    24: {'cor': 'preto', 'duzia': 3, 'coluna': 3, 'par_impar': 'par', 'alto_baixo': 'alto', 'terminal': 4, 'voisins': True, 'orphelins': False, 'tiers': False},
    25: {'cor': 'vermelho', 'duzia': 3, 'coluna': 1, 'par_impar': 'impar', 'alto_baixo': 'alto', 'terminal': 5, 'voisins': True, 'orphelins': True, 'tiers': False},
    26: {'cor': 'preto', 'duzia': 3, 'coluna': 2, 'par_impar': 'par', 'alto_baixo': 'alto', 'terminal': 6, 'voisins': False, 'orphelins': False, 'tiers': True},
    27: {'cor': 'vermelho', 'duzia': 3, 'coluna': 3, 'par_impar': 'impar', 'alto_baixo': 'alto', 'terminal': 7, 'voisins': True, 'orphelins': False, 'tiers': False},
    28: {'cor': 'preto', 'duzia': 3, 'coluna': 1, 'par_impar': 'par', 'alto_baixo': 'alto', 'terminal': 8, 'voisins': True, 'orphelins': True, 'tiers': False},
    29: {'cor': 'preto', 'duzia': 3, 'coluna': 2, 'par_impar': 'impar', 'alto_baixo': 'alto', 'terminal': 9, 'voisins': False, 'orphelins': False, 'tiers': True},
    30: {'cor': 'vermelho', 'duzia': 3, 'coluna': 3, 'par_impar': 'par', 'alto_baixo': 'alto', 'terminal': 0, 'voisins': True, 'orphelins': False, 'tiers': False},
    31: {'cor': 'preto', 'duzia': 3, 'coluna': 1, 'par_impar': 'impar', 'alto_baixo': 'alto', 'terminal': 1, 'voisins': True, 'orphelins': False, 'tiers': False},
    32: {'cor': 'vermelho', 'duzia': 3, 'coluna': 2, 'par_impar': 'par', 'alto_baixo': 'alto', 'terminal': 2, 'voisins': False, 'orphelins': False, 'tiers': True},
    33: {'cor': 'preto', 'duzia': 3, 'coluna': 3, 'par_impar': 'impar', 'alto_baixo': 'alto', 'terminal': 3, 'voisins': True, 'orphelins': True, 'tiers': False},
    34: {'cor': 'vermelho', 'duzia': 3, 'coluna': 1, 'par_impar': 'par', 'alto_baixo': 'alto', 'terminal': 4, 'voisins': False, 'orphelins': True, 'tiers': False},
    35: {'cor': 'preto', 'duzia': 3, 'coluna': 2, 'par_impar': 'impar', 'alto_baixo': 'alto', 'terminal': 5, 'voisins': True, 'orphelins': False, 'tiers': False},
    36: {'cor': 'vermelho', 'duzia': 3, 'coluna': 3, 'par_impar': 'par', 'alto_baixo': 'alto', 'terminal': 6, 'voisins': False, 'orphelins': True, 'tiers': False}
}

ESPELHOS = {
    6: 9, 9: 6, 12: 21, 19: 16, 16: 19, 21: 12, 23: 32, 32: 23, 29: 26, 26: 29,
    31: 13, 13: 31, 1: 10, 10: 1, 2: 20, 20: 2, 3: 30, 30: 3
}

# --- FUNÇÕES AUXILIARES ---
def escape_markdown_v2(text):
    if not isinstance(text, str): text = str(text)
    return re.sub(f"([{re.escape(r'_*[]()~`>#+=-|{}.!')}])", r"\\\1", text)

def get_neighbors(number, num_casas=1):
    if number is None or number not in ROULETTE_WHEEL_ORDER:
        return []
    idx = ROULETTE_WHEEL_ORDER.index(number)
    neighbors = set()
    length = len(ROULETTE_WHEEL_ORDER)
    for i in range(1, num_casas + 1):
        neighbors.add(ROULETTE_WHEEL_ORDER[(idx + i) % length])
        neighbors.add(ROULETTE_WHEEL_ORDER[(idx - i + length) % length])
    return sorted(list(neighbors))

def get_espelho(numero):
    return ESPELHOS.get(numero)

def get_prop(numero, prop_nome):
    if numero is None or numero not in NUMEROS_ROLETA:
        return None
    return NUMEROS_ROLETA[numero].get(prop_nome)

def get_all_props(numero):
    return NUMEROS_ROLETA.get(numero, {})

def gerar_assinatura_comportamental(numeros_alvo):
    assinatura = {}
    if not numeros_alvo:
        return assinatura

    propriedades = ['cor', 'duzia', 'coluna', 'par_impar', 'terminal', 'alto_baixo']
    
    for prop in propriedades:
        valores_prop = [get_prop(n, prop) for n in numeros_alvo if get_prop(n, prop) is not None]
        if not valores_prop:
            continue
        
        contagem = Counter(valores_prop)
        if contagem:
            mais_comum = contagem.most_common(1)[0][0]
            if contagem[mais_comum] / len(valores_prop) >= 0.7:
                assinatura[prop] = mais_comum

    return assinatura

def buscar_numeros_por_assinatura(assinatura):
    alvos = []
    if not assinatura:
        return []

    for numero, props in NUMEROS_ROLETA.items():
        if all(props.get(prop_nome) == valor for prop_nome, valor in assinatura.items()):
            alvos.append(numero)
    return alvos

def analisar_convergencia_simplificada(historico_completo):
    if len(historico_completo) < 30:
        return None
    
    gatilho_recente = historico_completo[0]
    contexto_recente_antes = historico_completo[1:6]
    
    if len(contexto_recente_antes) < 5:
        return None

    comportamentos_subsequentes_validados = []
    
    indices_gatilho = [i for i, num in enumerate(historico_completo) if num == gatilho_recente]
    
    for i in indices_gatilho:
        if i + 6 > len(historico_completo) or i < 3: continue
        
        contexto_antes_historico = historico_completo[i+1:i+6]

        if any(num in contexto_recente_antes for num in contexto_antes_historico):
            comportamento_subsequente_historico = historico_completo[i-1:i-4:-1]
            if len(comportamento_subsequente_historico) == 3:
                comportamentos_subsequentes_validados.append(comportamento_subsequente_historico)

    if len(comportamentos_subsequentes_validados) >= 2:
        alvos_totais = [item for sublist in comportamentos_subsequentes_validados for item in sublist]
        assinatura_final = gerar_assinatura_comportamental(alvos_totais)
        
        if assinatura_final:
            alvos_finais = buscar_numeros_por_assinatura(assinatura_final)
            
            alvos_pagos_recentemente = set(historico_completo[:5])
            alvos_nao_pagos = [num for num in alvos_finais if num not in alvos_pagos_recentemente]

            if alvos_nao_pagos:
                justificativa = (f"Padrão de convergência avançada. O gatilho '{gatilho_recente}' "
                                 f"foi confirmado por um número do contexto recente em {len(comportamentos_subsequentes_validados)} ocorrências. "
                                 f"A assinatura de alvos '{assinatura_final}' aponta para números que ainda não foram pagos.")
                return {
                    'tipo': 'Convergência Avançada',
                    'alvos': set(alvos_nao_pagos),
                    'justificativa': justificativa,
                    'assinatura': assinatura_final,
                    'gatilho': gatilho_recente
                }
    
    return None


def process_roulette(roulette, historico_completo):
    if len(historico_completo) < 30:
        return None
    
    print(f"NOVO NÚMERO {historico_completo[0]}")

    gatilho_recente = historico_completo[0]
    if gatilho_recente == 0:
        return None

    sugestao = analisar_convergencia_simplificada(historico_completo)
        
    if sugestao:
        alvos_principais = sugestao['alvos']
        if gatilho_recente in historico_completo[1:6]:
            print("DUPLICOU")
            return None
        
        if any(alvo in historico_completo[:6] for alvo in alvos_principais):
            return None
        
        entrada_completa = set(alvos_principais)
        gatilho_int = sugestao['gatilho']

        num_alvos = len(alvos_principais)
        if num_alvos == 1:
            num_vizinhos = 2
        elif 2 <= num_alvos <= 4:
            num_vizinhos = 1
        else:
            num_vizinhos = 0
            
        if num_vizinhos > 0:
            for alvo in list(alvos_principais):
                vizinhos = get_neighbors(alvo, num_vizinhos)
                for vizinho in vizinhos:
                    if len(entrada_completa) < 12:
                        entrada_completa.add(vizinho)
        
        entrada_completa.add(gatilho_int)
        espelho_gatilho = get_espelho(gatilho_int)
        if espelho_gatilho:
            entrada_completa.add(espelho_gatilho)
            
        if num_vizinhos == 0:
            for alvo in list(alvos_principais):
                espelho_alvo = get_espelho(alvo)
                if espelho_alvo:
                    entrada_completa.add(espelho_alvo)

        entrada_completa.add(0)

        sugestao['numeros_principais'] = sorted(list(alvos_principais))
        sugestao['numeros_completos'] = sorted(list(entrada_completa))
    
        return {
                "roulette_id": roulette['slug'],
                "roulette_name" : roulette["name"],
                "roulette_url" : roulette["url"],
                "pattern" : "IA REVESBOT",
                "triggers":historico_completo[1],
                "targets":[0],
                "bets":sugestao['numeros_completos'],
                "passed_spins" : 0,
                "spins_required" : 0,
                "spins_count": 0,
                "snapshot":historico_completo[:50],
                "status":"processing",
                "message" : "Gatilho encontrado!"
            }
    else:
        print("Nada encontrado")
        return None
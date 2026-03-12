import threading

import time 

from datetime import datetime


from patterns.score_v4 import RouletteAnalyzer


from typing import List, Dict
import logging

logger = logging.getLogger(__name__)



def process_roulette(roulette, historico) :
    """
    Processa roleta e cria sinal se condições forem atendidas.
    
    Args:
        roulette: Dados da roleta
        historico: Lista de números históricos
        full_results: Resultados completos da API
        sinais_recentes: Lista de sinais recentes da mesa (para análise de tendência)
                        Se None, sempre cria como 'processing'
    
    Returns:
        Signal dict ou None
    """

    if len(historico) <= 200:
        return None

    analyzer = RouletteAnalyzer(historico)

    
    # Último número que saiu
    base = historico[0]


    analise = analyzer.analisar_completo(base, quantidade=18)

    confianca = analise['confianca']


    bet = sorted(analise['previsao'])

  
    created_at = int(time.time())

    status = "processing"  # Default
    message = "Gatilho encontrado!"


    signal = {
        "roulette_id": roulette['slug'],
        "roulette_name" : roulette["name"],
        "roulette_url" : roulette["url"],
        "pattern" : f"SCORE",
        "triggers": historico[0],
        "targets":[*bet],
        "bets": bet,
        "passed_spins" : 0,
        "spins_required" : 0,
        "spins_count": 0,
        "gales" : 3,
        "score" : confianca,
        "snapshot":historico[:200],
        "status": status,
        "message" : message,
        "tags" : [],
        "created_at" : created_at,
        "timestamp" : created_at
    }


        
    return signal
from helpers.utils.filters import get_terminal, is_consecutive, get_neighbords, get_numbers_by_terminal

from helpers.utils.get_figure import get_figure

from datetime import datetime

import threading

import time 

from datetime import datetime


from patterns.score_v4 import RouletteAnalyzer


import requests
from typing import List, Dict, Tuple, Optional
import logging

logger = logging.getLogger(__name__)

BET_API_URL = "http://localhost:3000/api/bet"


# ══════════════════════════════════════════════════════════════════════════
# FUNÇÃO DE APOSTA VIA API (FIRE AND FORGET)
# ══════════════════════════════════════════════════════════════════════════

def _place_bet_sync(signal: dict) -> dict:
    """
    Envia aposta para a API externa via POST (versão síncrona com requests).
    """

    # Aguarda 2 segundos antes de enviar a aposta
    print(f"[BET API] ⏳ Aguardando 2 segundos antes de enviar aposta...")
    time.sleep(5)

    payload = {
        "bets": signal["bets"],
        #"bets": [0  ],
        "attempts": 1,
        "gales": 1,
        "roulette_url": signal['roulette_url'],
        "signal_id": str(signal.get("id", "")),
        "valor" : 0.5
    }
    
    print(f"[BET API] 🎰 Enviando aposta: {signal['roulette_name']} - {len(signal['bets'])} números")
    
    try:
        response = requests.post(
            BET_API_URL,
            json=payload,
            timeout=300
        )
        result = response.json()
        print(f"[BET API] ✅ Resposta: {result}")
        return result
    except Exception as e:
        print(f"[BET API] ❌ Erro ao chamar API de apostas: {e}")
        return {"success": False, "error": str(e)}


def _fire_bet_async(signal: dict):
    """
    Dispara a aposta em uma thread separada (fire-and-forget).
    Não bloqueia a execução principal.
    """
    def run_bet():
        try:
            _place_bet_sync(signal)
        except Exception as e:
            print(f"[BET THREAD] ❌ Erro na thread de aposta: {e}")
    
    thread = threading.Thread(target=run_bet, daemon=True)
    thread.start()
    print(f"[BET] 🚀 Aposta disparada em background para {signal['roulette_name']}")

def process_roulette(roulette, numbers) :

    if len(numbers) < 20:
        return None
    

    t1= get_terminal(numbers[0])
    t2= get_terminal(numbers[1])

    print(t1, t2, roulette["slug"])


    if t1 == t2 :
        t3 = get_terminal(numbers[2])

        terminais_t3  = get_numbers_by_terminal(t3)

        if t3 == t1 :
            return None
        
        if numbers[2] == 0:
            return None
        bet = []
        figuras = get_figure(t3)

        bet.extend(figuras)
        
        vizinhos_list = [m for n in terminais_t3 for m in get_neighbords(n)] 

        bet.extend(vizinhos_list)
        bet.extend(terminais_t3)

        bet.insert(0, 0)

        if t3 == 7 or t3 == 8:
            return None
        
        if numbers[0] == numbers[1] :
            return None

        if t3 == 9 : 
            t_adicional = get_numbers_by_terminal(6)

            bet.extend(t_adicional)

        if t3 == 4 :
            bet.insert(0, 1)
            bet.insert(0, 33)

        bet = sorted(set(bet))

        dt = datetime.now()
        created_at = int(dt.timestamp())



        status = "processing"

        signal = {
            "roulette_id": roulette['slug'],
            "roulette_name" : roulette["name"],
            "roulette_url" : roulette["url"],
            "pattern" : f"TERMINAIS-IGUAIS-{t3}",
            "triggers": numbers[0],
            "targets":[*bet],
            "bets": bet,
            "passed_spins" : 0,
            "spins_required" : 0,
            "spins_count": 0,
            "gales" : 3,
            "score" : 0,
            "snapshot":numbers[:200],
            "status": status,
            "message" : "Gatilho encontrado! ",
            "tags" : [],
            "temp_state" : None,    
            "created_at" : created_at,
            "timestamp" : created_at
        }
    
        #if status == "processing":
            #_fire_bet_async(signal)
        
        return signal

        

        



    
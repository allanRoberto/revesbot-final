
from helpers.utils.filters import first_index_after, get_terminal
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


def _place_bet_sync(signal: dict) -> dict:
    """
    Envia aposta para a API externa via POST (versão síncrona com requests).
    """

    # Aguarda 2 segundos antes de enviar a aposta
    print(f"[BET API] ⏳ Aguardando 2 segundos antes de enviar aposta...")
    time.sleep(3)

    payload = {
        "bets": signal["bets"],
        #"bets": [0  ],
        "attempts": 1,
        "gales": 1,
        "roulette_url": signal['roulette_url'],
        "signal_id": str(signal.get("id", "")),
        "valor" : 0.50
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

# DEFINIÇÃO DOS CAVALOS
CAVALOS = {
    "147": [1, 11, 21, 31, 4, 14, 24, 34, 7, 17, 27],
    "258": [2, 12, 22, 32, 5, 15, 25, 35, 8, 18, 28],
    "0369": [0, 10, 20, 30, 3, 13, 23, 33, 6, 16, 26, 36, 9, 19, 29]
}

# MAPEAMENTO DE NÚMERO PARA CAVALO
def obter_cavalo_do_numero(numero):
    """Retorna o cavalo ao qual o número pertence."""
    for cavalo, numeros in CAVALOS.items():
        if numero in numeros:
            return cavalo
    return None



def get_dozen(num: int) -> int:
        """Retorna a dúzia (1, 2 ou 3)"""
        if num == 0:
            return 0
        return (num - 1) // 12 + 1

def process_roulette(roulette, numbers, full_results) :

    if len(numbers) < 200 :
        return None
    base =numbers[0]

    if base == 0 : 
        return None 

    indice1 = first_index_after(numbers,base, 1)

    if not indice1 is None and indice1 > 10 :
        indice2 = first_index_after(numbers,base, indice1 + 1)

        if not indice2 is None and (indice2 - indice1) > 10 :
            numero1 = numbers[indice1 - 1]
            numero2 = numbers[indice2 - 1] 

            duzia1 = get_dozen(numero1)
            duzia2 = get_dozen(numero2)

            if duzia1 == duzia2 :
                cavalo1 = obter_cavalo_do_numero(numero1)
                cavalo2 = obter_cavalo_do_numero(numero2)
                
                if duzia1 == 1 :
                    bet = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
                elif duzia1 == 2 :
                    bet = [0, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24]
                elif duzia1 == 3 :
                    bet = [0, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36]        

                dt = datetime.now()
                created_at = int(dt.timestamp())    

                tem_comum = bool(set(numbers[1:3]) & set(bet))

                if not tem_comum : 
                    return None


                signal  = {
                    "roulette_id": roulette['slug'],
                    "roulette_name" : roulette["name"],
                    "roulette_url" : roulette["url"],
                    "pattern" : f"SINGLE_DOZE",
                    "triggers": numbers[0],
                    "targets":[*bet],
                    "bets": bet,
                    "passed_spins" : 0,
                    "spins_required" : 0,
                    "spins_count": 0,
                    "gales" : 3,
                    "score" : 0,
                    "snapshot":numbers[:200],
                    "status": "processing",
                    "message" : "Gatilho encontrado!",
                    "tags" : [],
                    "temp_state" : None,
                    "created_at" : created_at,
                    "timestamp" : created_at
                }
                


                #_fire_bet_async(signal)

                return signal

            


from helpers.utils.filters import get_terminal, get_numbers_by_terminal, first_index_after, get_neighbords, get_neighbords_color

from datetime import datetime

import threading

import time 

import requests


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
    time.sleep(4)

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

def process_roulette(roulette, numbers) :

    if len(numbers) < 200 :
        return None
    
    base  = numbers[0]

    indice1 = first_index_after(numbers, base, 1)

    if not indice1 is None :

        indice2 = first_index_after(numbers, base, indice1 + 1)

        if not indice2 is None :

            n1 = numbers[indice1 - 1]
            n2 = numbers[indice2 - 1]

            terminal_1 = get_terminal(n1)
            terminal_2 = get_terminal(n2)

            print(terminal_1, terminal_2)
            if terminal_1 == terminal_2 :

                bet = []
                vizinhos_1_1 = get_neighbords(n1)
                vizinhos_1_2 = get_neighbords_color(n1)
                vizinhos_2_1 = get_neighbords(n2)
                vizinhos_2_2 = get_neighbords(n2)   

                bet.extend(vizinhos_1_1)
                bet.extend(vizinhos_1_2)
                bet.extend(vizinhos_2_1)
                bet.extend(vizinhos_2_2)

                bet.insert(0, n1)
                bet.insert(0, n2)
                bet.insert(0, 0)

                bet = sorted(set(bet))

                bet = sorted(set(bet))

                dt = datetime.now()
                created_at = int(dt.timestamp())

                status = "processing"

                signal = {
                    "roulette_id": roulette['slug'],
                    "roulette_name" : roulette["name"],
                    "roulette_url" : roulette["url"],
                    "pattern" : f"TERMINAIS-IGUAIS",
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

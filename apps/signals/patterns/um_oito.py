from helpers.utils.filters import get_terminal
import time

def process_roulette(roulette, numbers) :
    numero1 = get_terminal(numbers[0])
    numero2 = get_terminal(numbers[1])

    print(numero1, numero2)

    slug = roulette['slug']

    bets = [0, 4, 7, 9, 15, 18, 19, 22, 29, 31]

    if numero1 == 8 and numero2 == 1 :
       

        return {
        "roulette_id": slug,
        "roulette_name": roulette["name"],
        "roulette_url": roulette["url"],
        "pattern": "NUMEROS_PUXANDO",
        "triggers": [numbers[0]],
        "targets": [*bets],
        "bets": bets,
        "status": "processing",
        "gales": 3,
        "passed_spins": 0,
        "spins_required": 0,
        "snapshot": numbers[:1000],
        "score": 0,
        "message": f"[PAI] Aguardando gatilho...",
        "tags": ["numeros_puxando", "parent"],
        "created_at" : int(time.time()),
        "timestamp" : int(time.time()),
        "temp_state": {
            "is_parent": True,
            "max_activations": 0,
            "max_spins": 0,
            "gales_per_child": 0,
            "current_activation": 0,
            "child_active": False,
            "active_child_id": None,
            "last_win_number": None,
            "children_ids": [],
            "total_wins": 0,
            "total_losses": 0,
        }
    }

    elif numero1 == 1 and numero2 == 8:

        return {
            "roulette_id": slug,
            "roulette_name": roulette["name"],
            "roulette_url": roulette["url"],
            "pattern": "NUMEROS_PUXANDO",
            "triggers": [numbers[0]],
            "targets": [*bets],
            "bets": bets,
            "status": "processing",
            "gales": 3,
            "passed_spins": 0,
            "spins_required": 0,
            "snapshot": numbers[:1000],
            "score": 0,
            "message": f"[PAI] Aguardando gatilho...",
            "tags": ["numeros_puxando", "parent"],
            "created_at" : int(time.time()),
            "timestamp" : int(time.time()),
            "temp_state": {
                "is_parent": True,
                "max_activations": 0,
                "max_spins": 0,
                "gales_per_child": 0,
                "current_activation": 0,
                "child_active": False,
                "active_child_id": None,
                "last_win_number": None,
                "children_ids": [],
                "total_wins": 0,
                "total_losses": 0,
            }
        }
    else : 
        return None



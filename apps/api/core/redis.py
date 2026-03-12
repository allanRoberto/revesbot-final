import json
import time
import uuid

from types import SimpleNamespace


from api.core.redis_client import r

def save_signal(
    id : str,
    roulette_id: str, 
    roulette_name: str,
    roulette_url: str,
    triggers: int | list[int],
    targets: int | list[int],
    bets: int | list[int],
    snapshot: list[int],
    status: str,
    pattern=str,
    passed_spins=int,
    spins_required=int
):
    # 1) Normaliza triggers/targets/bets para sempre serem listas
    if not isinstance(triggers, list):
        triggers = [triggers]
    if not isinstance(targets, list):
        targets = [targets]
    if not isinstance(bets, list):
        bets = [bets]


    # 3) Monta o dict do sinal
    new_signal = {
        "id":               id,
        "roulette_id":      roulette_id,
        "roulette_name":    roulette_name,
        "roulette_url":     roulette_url,
        "pattern":          pattern,
        "triggers":         triggers,
        "targets":          targets,
        "bets":             bets,
        "status":           status,
        "history":          snapshot[:30],
        "snapshot":         snapshot,
        "passed_spins":     passed_spins,
        "spins_after_trigger":     passed_spins,
        "spins_required":   spins_required,
        "wait_spins_after_trigger": 0,
        "attempts": 0,
        "broadcasted":      False,
        "message":          "Aguardando gatilho",
        "created_at":       int(time.time()),
        "updated_at":       int(time.time()),
        "timestamp":        int(time.time()),
    }


    return SimpleNamespace(**new_signal)

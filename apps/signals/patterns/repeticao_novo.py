from helpers.utils.filters import (
    is_consecutive,
    is_skipped_sequence,
    any_consecutive,
    same_terminal,
    first_index_after,
    appears_in_slice
)

from helpers.utils.get_neighbords import get_neighbords
from helpers.utils.get_mirror import get_mirror
from typing import Callable, List, Tuple


debug = True

Filter = Tuple[str, str, Callable[[], bool]]

FILTER_SWITCHES = {
    "proximidade": True,
    "espelho": True,
    "vizinhos": True,
    "terminais": False,
    "numeros_restritos": True,
    "posicoes": False,
}


def run_filters(filters: List[Filter], debug: bool = False) -> bool:
    """Retorna *True* se algum filtro bloquear (e exibe qual)."""
    for categoria, descricao, cond in filters:
        if not FILTER_SWITCHES.get(categoria, True):
            continue  # grupo desligado
        try:
            if cond():
                if debug:
                    print(f"[{categoria.upper()}] {descricao}")
                return True  # BLOQUEADO
        except Exception as e:
            if debug:
                print(f"[ERRO] {categoria} – {descricao}: {e}")
            return True      # bloqueia por segurança
    return False  # passou

def process_roulette(roulette, numbers) : 

     idxs = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9)
     p0, p1, p2, p3, p4, p5, p6, p7, p8, p9 = [numbers[i] for i in idxs] 

     

     target1 = p0
     target2 = p1
     pos2 = p2
     pos3 = p3
     pos4 = p4
     pos5 = p5
     check1 = p6
     check2 = p7
     trigger = check2
     pos7 = p7
     pos8 = p8

     mirror_p2 = get_mirror(pos2)
     mirror_trigger = get_mirror(trigger)
     mirror_check1 = get_mirror(check1)
     mirror_check2 = get_mirror(check2)
     mirror_p7 = get_mirror(pos7)
     mirror_p8 = get_mirror(pos8)
          # Pré‑condição da lógica original
     if not same_terminal(check1, check2):
          return None  # nada a filtrar

     
     filters: List[Filter] = []

     # === PROXIMIDADE =====================================================
     if FILTER_SWITCHES["proximidade"]:
          filters += [
               ("proximidade", "[CODIGO 01] - Alvos não podem ser consecutivos", lambda: is_consecutive(target1, target2)),
          ]

     # === ESPELHO =========================================================
     if FILTER_SWITCHES["espelho"]:
          filters += [
               ("espelho", "[CODIGO 03] - Alvos não podem ser vizinhos", lambda: (target2 in get_mirror(target1))),
               ("espelho", "[CODIGO 03] - Alvos não podem ser vizinhos", lambda: (target1 in get_mirror(target2))),

          ]

   

   
     # === VIZINHOS ========================================================
     if FILTER_SWITCHES["vizinhos"]:
          filters += [
               ("proximidade", "[CODIGO 02] - Alvos não podem ser vizinhos", lambda: (target1 in get_neighbords(target2))),
               ("proximidade", "[CODIGO 03] - Alvos não podem ser vizinhos", lambda: (target2 in get_neighbords(target1))),
          ]

     # === NÚMEROS RESTRITOS ===============================================
     if FILTER_SWITCHES["numeros_restritos"]:
          filters += [
               ("numeros_restritos", "Zero/36 presente", lambda: any(n in {0, 36} for n in (target1, target2, check1, check2))),
          ]

     # ------------------------------------------------------------------
     
     bloqueado = run_filters(filters, debug)
    
     if(bloqueado) : 
          return None
          
     if(target1 == 0 or target2 == 0) : 
          return None
     
     target1_neighbords = get_neighbords(target1)
     target2_neighbords = get_neighbords(target2)

     bet = [target1, target2, *target1_neighbords, *target2_neighbords]    
     mirror_list = [m for n in bet for m in get_mirror(n)]

     bet.extend(mirror_list)

     bet.insert(0, 0)

     bet = sorted(set(bet))

     return {
          "roulette_id": roulette['slug'],
          "roulette_name" : roulette["name"],
          "roulette_url" : roulette["url"],
          "pattern" : "REPETICAO",
          "triggers":[trigger],
          "targets":[target1, target2],
          "bets":bet,
          "passed_spins" : 0,
          "spins_required" : 0,
          "spins_count": 0,
          "snapshot":numbers[:50],
          "status":"waiting",
          "message" : "Gatilho encontrado!"
     }
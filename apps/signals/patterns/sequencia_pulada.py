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
    "espelho": False,
    "vizinhos": True,
    "terminais": False,
    "numeros_restritos": True,
    "posicoes": True,
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

     pos1 = p1
     pos2 = p2
     target = p3 #Alvo para formação da aposta
     check1 = p4 #Sequência
     check2 = p5 #Sequência
     trigger = p6 #Gatilho
     pos7 = p7
     pos8 = p8
     pos9 = p9

     mirror_p1 = get_mirror(pos1)
     mirror_p2 = get_mirror(pos2)
     mirror_target = get_mirror(target)
     mirror_trigger = get_mirror(trigger)
     mirror_check1 = get_mirror(check1)
     mirror_check2 = get_mirror(check2)
     mirror_p7 = get_mirror(pos7)
     mirror_p8 = get_mirror(pos8)


          # Pré‑condição da lógica original
     if not is_skipped_sequence(check1, check2):
          return None  # nada a filtrar


     filters: List[Filter] = []

     # === PROXIMIDADE =====================================================
     if FILTER_SWITCHES["proximidade"]:
          filters += [
               ("proximidade", "Gatilho e sequencia 1 não pode ser consecutivos", lambda: is_consecutive(trigger, check1)),
               ("proximidade", "Gatilho e sequencia 1 não pode ser consecutivos", lambda: is_consecutive(trigger, check2)),
               ("proximidade", "pos7 e trigger não pode ser consecutivo",   lambda: is_consecutive(trigger, pos7)),
               ("proximidade", "O pos8  e trigger não pode ser consecutivo",    lambda: is_consecutive(pos8, trigger)),
               ("proximidade", "Sequencia pulada entre target e pos2", lambda: is_skipped_sequence(target, pos2)),
               ("proximidade", "Sequencia pulada entre target e pos2", lambda: is_skipped_sequence(trigger, pos7)),


               ("proximidade", "Alvo e sequencia 1 não pode ser consecutivo",  lambda: is_consecutive(check1, target)),
               ("proximidade", "Alvo e sequencia 1 não pode ser consecutivo",  lambda: is_consecutive(check2, target)),
               ("proximidade", "O número atrás do gatilho não pode formar uma sequência com o sequencia 1",    lambda: is_consecutive(pos7, check2)),
               ("proximidade", "O gatilho não pode ter uma sequencia atrás",      lambda: is_consecutive(pos7, pos8)),
               ("proximidade", "O gatinho nao pode ter uma sequencia atrás pulando um número",      lambda: is_consecutive(pos8, pos9)),
               ("proximidade", "O alvo nao pode formar uma sequencia",    lambda: is_consecutive(pos2, target)),
               ("proximidade", "O alvo e o gatilho nao pode formar uma sequencia", lambda: is_consecutive(trigger, target)),

               # any_consecutive envolvendo espelhos
               ("proximidade", "mirror_trigger≅mirror_check1", lambda: any(any_consecutive(a, mirror_check1) for a in mirror_trigger)),
               ("proximidade", "mirror_trigger≅mirror_check2", lambda: any(any_consecutive(a, mirror_check2) for a in mirror_trigger)),
               ("proximidade", "trigger≅mirror_target", lambda: any(is_consecutive(a, check1) for a in mirror_trigger)),
               ("proximidade", "trigger≅mirror_target", lambda: any(is_consecutive(a, check2) for a in mirror_trigger)),
               ("proximidade", "trigger≅mirror_target", lambda: any(is_consecutive(a, trigger) for a in mirror_target)),
               ("proximidade", "trigger≅mirror_target", lambda: any(is_consecutive(a, target) for a in mirror_trigger)),
               ("proximidade", "trigger≅mirror_target", lambda: any(is_consecutive(a, pos7) for a in mirror_trigger)),
               ("proximidade", "trigger≅mirror_target", lambda: any(is_consecutive(a, check1) for a in mirror_target)),
               ("proximidade", "trigger≅mirror_target", lambda: any(is_consecutive(a, check2) for a in mirror_target)),
          ]

     # === ESPELHO =========================================================
     if FILTER_SWITCHES["espelho"]:
          filters += [
               ("espelho", "target ∈ mirror_p7",           lambda: target in mirror_p7),
               ("espelho", "p7 ∈ mirror_target",           lambda: pos7 in mirror_target),
               ("espelho", "trigger ∈ mirror_target",      lambda: trigger in mirror_target),
               ("espelho", "pos2 ∈ mirror_trigger",        lambda: pos2 in mirror_trigger),
               ("espelho", "trigger ∈ mirror_p2",          lambda: trigger in mirror_p2),
               ("espelho", "check2 ∈ mirror_p8",           lambda: check2 in mirror_p8),
               ("espelho", "check2 ∈ mirror_p7",           lambda: check2 in mirror_p7),
               ("espelho", "check1 ∈ mirror_p8",           lambda: check1 in mirror_p8),
               ("espelho", "check1 ∈ mirror_p7",           lambda: check1 in mirror_p7),
               ("espelho", "trigger ∈ mirror_check1",      lambda: trigger in mirror_check1),
               ("espelho", "trigger ∈ mirror_check2",      lambda: trigger in mirror_check2),
               ("espelho", "check1 ∈ mirror_p2",           lambda: check1 in mirror_p2),
               ("espelho", "pos2 ∈ mirror_check1",         lambda: pos2 in mirror_check1),
               ("espelho", "pos7 ∈ mirror_check2",         lambda: pos7 in mirror_check2),
               ("espelho", "trigger ∈ mirror_p7",          lambda: trigger in mirror_p7),
               ("espelho", "target ∈ mirror_p2",           lambda: target in mirror_p2),
          ]

     # === TERMINAIS =======================================================
     if FILTER_SWITCHES["terminais"]:
          filters += [
               ("terminais", "terminal pos7=pos8",      lambda: same_terminal(pos7, pos8)),
               ("terminais", "terminal pos7=trigger",   lambda: same_terminal(pos7, trigger)),
               ("terminais", "terminal target=check1",  lambda: same_terminal(target, check1)),
               ("terminais", "terminal target=pos2",    lambda: same_terminal(target, pos2)),
               ("terminais", "terminal target=pos2",    lambda: same_terminal(target, trigger)),
               ("terminais", "terminal target=pos2",    lambda: same_terminal(target, pos7)),
               ("terminais", "terminal target=pos2",    lambda: same_terminal(pos7, pos2)),
               ("terminais", "terminal target=pos2",    lambda: same_terminal(check2, trigger)),
               ("terminais", "terminal target=pos2",    lambda: same_terminal(check1, target)),
          ]

     # === POSIÇÕES (igualdade) ============================================
     if FILTER_SWITCHES["posicoes"]:
          filters += [
               ("posicoes", "pos2 == trigger",   lambda: pos2 == trigger),
               ("posicoes", "Gatilho nao pode ter repeticao atrás dele", lambda: (trigger == pos7)),
               ("posicoes", "pos8 == pos7",      lambda: pos8 == pos7),
               ("posicoes", "trigger == pos8",   lambda: trigger == pos8),
               ("posicoes", "check1 == pos7",    lambda: check1 == pos7),
               ("posicoes", "check1 == pos8",    lambda: check1 == pos8),
               ("posicoes", "pos2 == check1",    lambda: pos2 == check1),
               ("posicoes", "pos2 == pos7",      lambda: pos2 == pos7),
               ("posicoes", "pos7 == target",    lambda: pos7 == target),
               ("posicoes", "target == pos2",    lambda: target == pos2),
               ("posicoes", "target == p7",      lambda: target == p7),
               ("posicoes", "target == p8",      lambda: target == p8),
               ("posicoes", "pos2 == pos1",      lambda: pos2 == pos1),
               ("posicoes", "trigger == target", lambda: trigger == target),
               ("posicoes", "check1 == trigger", lambda: check1 == trigger),
               ("posicoes", "check2 == trigger", lambda: check2 == trigger),
               ("posicoes", "gatilho ativado muito cedo", lambda: pos1 == trigger or pos2 == trigger),
               ("posicoes", "alternancia com a sequencia", lambda: pos7 == check2),
               ("posicoes", "alternancia com a sequencia", lambda: check1 == pos7),
               ("posicoes", "alternancia com a sequencia", lambda: check1 == pos8),
               ("posicoes", "alternancia com a sequencia", lambda: check2 == pos7),
               ("posicoes", "alternancia com a sequencia", lambda: check2 == pos8),
          ]

     # === VIZINHOS ========================================================
     if FILTER_SWITCHES["vizinhos"]:
          filters += [
               ("vizinhos", "trigger≅mirror_target", lambda: any((a == check1) for a in get_neighbords(trigger))),
               ("vizinhos", "trigger≅mirror_target", lambda: any((a == check2) for a in get_neighbords(trigger))),
          ]

     # === NÚMEROS RESTRITOS ===============================================
     if FILTER_SWITCHES["numeros_restritos"]:
          filters += [
               ("numeros_restritos", "Zero/36 presente", lambda: any(n in {0, 36} for n in (target, trigger, pos7, check1, check2))),
          ]

          # ------------------------------------------------------------------
     bloqueado = run_filters(filters, debug)
    
     if(bloqueado) : 
          return None
          
     target1  =  target - 2
     target2  =  target + 2

     if(target1 == 0 or target2 == 0) : 
          return None
     
     if(trigger == target1 or trigger == target2) : 
          return None
     
     if (is_consecutive(trigger, target1) or is_consecutive(trigger, target2)) :
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
          "pattern" : "SEQUENCIA PULADA",
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
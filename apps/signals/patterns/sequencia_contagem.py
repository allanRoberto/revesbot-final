from helpers.utils.filters import (
    is_consecutive,
    any_consecutive,
    same_terminal,
    first_index_after,
    appears_in_slice
)

from helpers.utils.get_neighbords import get_neighbords
from helpers.utils.get_mirror import get_mirror
from typing import Callable, List, Tuple


debug = False

Filter = Tuple[str, str, Callable[[], bool]]

FILTER_SWITCHES = {
    "proximidade": True,
    "espelho": True,
    "vizinhos": True,
    "terminais": True,
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

    #Encontrar mais 3 ocorências de um número dentro de um range de 100 números 
    if len(numbers) < 50 :
        return None

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

    index_trigger = first_index_after(numbers, trigger, 7);


    if trigger in (1, 10) : 
        return None
    
    if(is_consecutive(numbers[10], numbers[11])) :
        return None
    
    if(appears_in_slice(0, numbers[:2], 0, 2) and appears_in_slice(0, numbers[7:10], 0, 3)) :
        return None

    if(check1 > check2) : 
        spins_count = check1 + 1
    else : 
        spins_count = check1 - 1


    spins_count_neighbords = get_neighbords(spins_count)
    mirror_spin_count = get_mirror(spins_count)
    target_neighbords = get_neighbords(target)

     # Pré‑condição da lógica original
    if not is_consecutive(check1, check2):
        return None  # nada a filtrar


    filters: List[Filter] = []

    # === PROXIMIDADE =====================================================
    if FILTER_SWITCHES["proximidade"]:
        filters += [
            ("proximidade", "trigger≅check1", lambda: is_consecutive(trigger, check1)),
            ("proximidade", "trigger≅check2", lambda: is_consecutive(trigger, check2)),
            ("proximidade", "trigger≅pos7",   lambda: is_consecutive(trigger, pos7)),
            ("proximidade", "check1≅target",  lambda: is_consecutive(check1, target)),
            ("proximidade", "check2≅target",  lambda: is_consecutive(check2, target)),
            ("proximidade", "pos7≅check2",    lambda: is_consecutive(pos7, check2)),
            ("proximidade", "pos7≅pos8",      lambda: is_consecutive(pos7, pos8)),
            ("proximidade", "pos8≅pos9",      lambda: is_consecutive(pos8, pos9)),
            ("proximidade", "pos2≅target",    lambda: is_consecutive(pos2, target)),
            ("proximidade", "trigger≅target", lambda: is_consecutive(trigger, target)),
            ("proximidade", "trigger≅spins_count", lambda: is_consecutive(trigger, spins_count)),
            ("proximidade", "spins_count≅target",  lambda: is_consecutive(spins_count, target)),
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
            
            
            ("proximidade", "mirror_target≅mirror_spin_count", lambda: any(any_consecutive(a, mirror_spin_count) for a in mirror_target)),
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
        ]

    # === POSIÇÕES (igualdade) ============================================
    if FILTER_SWITCHES["posicoes"]:
        filters += [
            ("posicoes", "pos2 == trigger",   lambda: pos2 == trigger),
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
            ("posicoes", "spins_count == pos7", lambda: spins_count == pos7),
            ("posicoes", "pos2 == spins_count", lambda: pos2 == spins_count),
            ("posicoes", "pos1 == spins_count", lambda: pos1 == spins_count),
            ("posicoes", "spins_count fora do intervalo", lambda: spins_count > 36 or spins_count < 1),
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
            ("vizinhos", "pos2 vizinho de spins_count", lambda: pos2 in get_neighbords(spins_count)),
            ("vizinhos", "pos1 vizinho de spins_count", lambda: pos1 in get_neighbords(spins_count)),
            ("vizinhos", "target vizinho de spins_count", lambda: target in spins_count_neighbords),
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


    bet = [target, spins_count, *target_neighbords, *spins_count_neighbords]
    
    mirror_list = [m for n in bet for m in get_mirror(n)]

    bet.extend(mirror_list)

    bet.insert(0, 0)

    bet = sorted(set(bet))

    return {
            "roulette_id": roulette['slug'],
            "roulette_name" : roulette["name"],
            "roulette_url" : roulette["url"],
            "pattern" : "SEQUENCIA",
            "triggers":[trigger],
            "targets":[target, spins_count],
            "bets":bet,
            "passed_spins" : 0,
            "spins_required" : spins_count,
            "spins_count": spins_count,
            "snapshot":numbers[:50],
            "status":"waiting",
    }

        


     
          
from helpers.utils.filters import (
    is_consecutive,
    is_skipped_sequence,
    get_terminal,
    soma_digitos,
)

from helpers.utils.get_neighbords import get_neighbords
from helpers.utils.get_mirror import get_mirror
from typing import Callable, List, Tuple


debug = True

Filter = Tuple[str, str, Callable[[], bool], str]

def run_filters(filters: List[Filter], debug: bool = False) -> Tuple[bool, List[str]]:
    """Retorna *True* se algum filtro bloquear e lista de todas as tags identificadas."""
    tags_identificadas = []
    
    for categoria, descricao, cond, tag in filters:
        if not FILTER_SWITCHES.get(categoria, True):
            continue  # grupo desligado
        try:
            if cond():
                tags_identificadas.append(tag)
                if debug:
                    print(f"[{categoria.upper()}] {descricao} - TAG: {tag}")
                # Por enquanto não bloqueia, apenas coleta tags
        except Exception as e:
            if debug:
                print(f"[ERRO] {categoria} — {descricao}: {e}")
    
    return False, tags_identificadas  # Nunca bloqueia por enquanto, apenas retorna as tags

FILTER_SWITCHES = {
    "terminal": True,
    "soma" : True,
    "repetition" : True,
    "consecutive" : True,
    "number_restrict" : True,
    "skipped_sequence" : True
}
def run_all_filters(numbers) :


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
 
    trigger_terminal = get_terminal(trigger)
    pos7_terminal = get_terminal(pos7)
    pos8_terminal = get_terminal(pos8)
    check1_terminal = get_terminal(check1)
    check2_terminal = get_terminal(check2)


    filters: List[Filter] = []

    if FILTER_SWITCHES["consecutive"]:
            filters += [
               ("consecutive", "Gatilho não pode ter sequencia de terminais", lambda: is_consecutive(trigger_terminal, pos7_terminal), "consecutivo_terminal_atras_com_gatilho"),
               ("consecutive", "Gatilho não pode ter sequencia de terminais", lambda: is_consecutive(pos7_terminal, pos8_terminal), "consecutivo_atras_gatilho"),
               ("consecutive", "Gatilho não pode ter sequencia de terminais", lambda: is_consecutive(check2_terminal, trigger_terminal), "consecutivo_terminal_frente_com_gatilho"),
               ("consecutive", "Gatilho não pode ter sequencia de terminais", lambda: is_consecutive(target, trigger), "consecutivo_gatilho_alvo"),
            ]

    if FILTER_SWITCHES["repetition"]:
            filters += [
               ("repetition", "Gatilho não pode ter sequencia de terminais", lambda: trigger_terminal == pos7_terminal, "repeticao_terminal_atras_com_gatilho"),
               ("repetition", "Gatilho não pode ter sequencia de terminais", lambda: pos8_terminal == pos7_terminal, "repeticao_terminal_atras_gatilho"),
               ("repetition", "Gatilho não pode ter sequencia de terminais", lambda: trigger_terminal == check2_terminal, "repeticao_terminal_frente_com_gatilho"),
               ("repetition", "Gatilho não pode ter sequencia de terminais", lambda: target == trigger, "repeticao_terminal_gatilho"),
            ]

    if FILTER_SWITCHES.get("alternance", False):
            filters += [
               ("alternance", "Gatilho não pode ter sequencia de terminais", lambda: trigger_terminal == pos8_terminal, "alternancia_repeticao_terminal_atras_com_gatilho"),
               ("alternance", "Gatilho não pode ter sequencia de terminais", lambda: is_consecutive(trigger_terminal, pos8_terminal), "alternancia_consecutivo_terminal_frente_com_gatilho"),
            ]    

    if FILTER_SWITCHES["number_restrict"]:
            filters += [
               ("number_restrict", "Gatilho não pode ter sequencia de terminais", lambda: trigger == 0, "gatilho_0"),
               ("number_restrict", "Gatilho não pode ter sequencia de terminais", lambda: target == 0, "alvo_0"),
               ("number_restrict", "Gatilho não pode ter sequencia de terminais", lambda: check1 == 0, "check1_0"),
               ("number_restrict", "Gatilho não pode ter sequencia de terminais", lambda: check2 == 0, "check2_0"),
               ("number_restrict", "Gatilho não pode ter sequencia de terminais", lambda: pos2 == 0, "pos2_0"),
               ("number_restrict", "Gatilho não pode ter sequencia de terminais", lambda: pos7 == 0, "pos7_0"),
               ("number_restrict", "Gatilho não pode ter sequencia de terminais", lambda: pos8 == 0, "pos8_0"),
            ]

    if FILTER_SWITCHES["skipped_sequence"]:
            filters += [
               ("skipped_sequence", "Gatilho não pode ter sequencia pulada", lambda: is_skipped_sequence(trigger, check2), "seq_pulada_trigger_check2"),
               ("skipped_sequence", "Gatilho não pode ter sequencia pulada", lambda: is_skipped_sequence(target, check1), "seq_pulada_target_check1"),
               ("skipped_sequence", "Gatilho não pode ter sequencia pulada", lambda: is_skipped_sequence(target, pos2), "seq_pulada_target_pos2"),
               ("skipped_sequence", "Gatilho não pode ter sequencia pulada", lambda: is_skipped_sequence(trigger, pos7), "seq_pulada_trigger_pos7"),
            ]
            
    if FILTER_SWITCHES["soma"]:
            filters += [
               ("soma", "Soma do check1 nao pode ser igual a soma do alvo", lambda: (soma_digitos(target) == soma_digitos(check1)), "soma_igual_target_check1"),
               ("soma", "Soma de check2 nao pode ser igual soma de pos2", lambda: (soma_digitos(check1) == soma_digitos(pos2)), "soma_igual_check1_pos2"),
               ("soma", "Antes do gatilho não pode ter repetição de terminais", lambda: (soma_digitos(check2) == soma_digitos(pos7)), "soma_igual_check2_pos7"),
               ("soma", "Antes do gatilho não pode ter repetição de terminais", lambda: (soma_digitos(check2) == soma_digitos(target)), "soma_igual_check2_target"),
               ("soma", "Antes do gatilho não pode ter repetição de terminais", lambda: (soma_digitos(pos1) == soma_digitos(pos2)), "soma_igual_pos1_pos2"),
               ("soma", "Antes do gatilho não pode ter repetição de terminais", lambda: (soma_digitos(target) == soma_digitos(trigger)), "soma_igual_target_trigger"),
               ("soma", "Antes do gatilho não pode ter repetição de terminais", lambda: (soma_digitos(target) == trigger), "soma_target_igual_trigger"),
               ("soma", "Antes do gatilho não pode ter repetição de terminais", lambda: (soma_digitos(trigger) == target), "soma_trigger_igual_target"),
               ("soma", "Antes do gatilho não pode ter repetição de terminais", lambda: (is_consecutive(soma_digitos(target), soma_digitos(check1))), "soma_consecutiva_target_check1"),
               ("soma", "Antes do gatilho não pode ter repetição de terminais", lambda: (is_consecutive(soma_digitos(trigger), soma_digitos(check2))), "soma_consecutiva_trigger_check2"),
               ("soma", "Antes do gatilho não pode ter repetição de terminais", lambda: (soma_digitos(trigger) == soma_digitos(pos7)), "soma_igual_trigger_pos7"),
               ("soma", "Antes do gatilho não pode ter repetição de terminais", lambda: (soma_digitos(trigger) == soma_digitos(check2)), "soma_igual_trigger_check2"),
               ("soma", "Antes do gatilho não pode ter repetição de terminais", lambda: (is_consecutive(soma_digitos(target), soma_digitos(pos2))), "soma_consecutiva_target_pos2"),
            ]

    bloqueado, tags = run_filters(filters, debug)

    return [bloqueado, tags]
from typing import Any, Dict, List, Optional
import traceback
import inspect
import json

from core.redis import save_signal
from helpers.utils.redis_client import r

# Importe todos os seus padrões aqui
from patterns import (
    subtracao_api,
    # blackhorse,
    # api_monitor,
    # cinco_bases,
    # cavalos_faltantes,
    # terminal_anterior,
    # terminal_anterior_v2,
    # puxados_stride,
    # puxados_v3,
    # terminal_zero,
    # alternancia_terminal,
    # soma_repeticao_terminais,
    # patchoko,
    # puxou_cavalo_todos,
    # puxou_cavalo,
    # patchoko_rep,
    # patchoko_seq,
    # chat_rick_v2,
    # um_oito,
    # ultimo,
    # single_dose,
    # numeros,
    # rick,
    # tresfichas,
    # rick2,
    # puxou_terminais_iguais,
    # numeros_puxando,
    # ensemble_adapter,
)

# Lista de módulos de patterns que possuem a função process_roulette
ALL_PATTERNS = [
    # ================= PATTERNS ATIVOS =================
    subtracao_api,
    # ================= PATTERNS INATIVOS =================
    # blackhorse,
    # api_monitor,
    # cinco_bases,
    # cavalos_faltantes,
    # um_oito,
    # ultimo,
    # rick,
    # puxados_stride,
    # puxados_v3,
    # patchoko,
    # patchoko_rep,
    # patchoko_seq,
    # alternancia_terminal,
    # soma_repeticao_terminais,
    # puxou_cavalo_todos,
    # chat_rick_v2,
    # terminal_anterior_v2,
    # tresfichas,
    # rick2,
    # puxou_terminais_iguais,
    # numeros,
    # numeros_puxando
    # ensemble_adapter
]


def _has_active_signal_for_roulette(slug: str) -> bool:
    """
    Verifica se existe algum sinal ativo para a mesa (slug).
    Retorna True se existir sinal ativo, False caso contrário.
    """
    try:
        # Pega todos os sinais ativos
        active_signals = r.hgetall("signals:active")
        
        if not active_signals:
            return False
        
        # Verifica se algum sinal é desta mesa
        for signal_id, signal_data in active_signals.items():
            signal = json.loads(signal_data)
            if signal.get("roulette_id") == slug:
                # Existe sinal ativo desta mesa
                return True
        
        return False
    except Exception as e:
        print(f"[_has_active_signal_for_roulette] Erro: {e}")
        return True  # Em caso de erro, bloqueia por segurança


def run_all_patterns(
    roulette,
    results: List[int],
    full_results: Optional[List[Dict]] = None,
    diag_ctx: Optional[Dict[str, Any]] = None,
):
    """
    Executa todos os padrões definidos para uma roleta específica.

    :param roulette: Objeto com slug, nome e url da roleta
    :param results: Lista de inteiros com o histórico recente da roleta
    :param full_results: (Opcional) Lista de objetos completos com _id, timestamp, etc
    """

    slug = roulette["slug"]

    # Verifica se já existe sinal ativo para esta mesa
    
    if _has_active_signal_for_roulette(slug):
        return

    diag_state: Dict[str, Any] = diag_ctx if isinstance(diag_ctx, dict) else {}
    diag_state.setdefault("signal_generated", False)
    diag_state.setdefault("signal_saved", False)
    diag_state.setdefault("signal_pattern", None)
    diag_state.setdefault("signal_id", None)
    diag_state.setdefault("error", None)

    for pattern in ALL_PATTERNS:
        try:
            # Verificar quantos parâmetros o padrão aceita
            sig = inspect.signature(pattern.process_roulette)
            num_params = len(sig.parameters)
            
            if num_params >= 3:
                # Padrão aceita full_results mas não sinais_recentes
                signal = pattern.process_roulette(roulette, results, full_results)
            else:
                # Padrão antigo, só 2 params
                signal = pattern.process_roulette(roulette, results)

            if not signal:
                continue

            diag_state["signal_generated"] = True
            diag_state["signal_pattern"] = signal.get("pattern", getattr(pattern, "__name__", "UNKNOWN"))

            # Se chegou aqui, não tem sinal ativo, pode salvar
            signal_id = save_signal(
                signal["roulette_id"],
                signal["roulette_name"],
                signal["roulette_url"],
                signal["triggers"],
                signal["targets"],
                signal["bets"],
                signal["snapshot"],
                signal["status"],
                signal.get("pattern", "UNKNOWN"),
                signal["passed_spins"],
                signal["spins_required"],
                signal["gales"],
                signal["score"],
                signal["message"],
                signal["temp_state"],
                signal["created_at"],
                signal["timestamp"],
                signal["tags"]
            )
            diag_state["signal_saved"] = bool(signal_id)
            diag_state["signal_id"] = signal_id

            # Assim que salvar 1 sinal, para o loop
            # (não processa os outros padrões neste spin)
            break

        except Exception as e:
            diag_state["error"] = str(e)
            print(f"[run_all_patterns] Erro ao executar padrões para {roulette['slug']}: {str(e)}")
            traceback.print_exc()

    return diag_state

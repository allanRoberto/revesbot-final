"""
Pattern: Números que se Puxam
Análise estatística em 6 camadas para identificar grupos de números correlacionados

Integra com run_all_patterns.py
"""

from datetime import datetime
from typing import List, Dict, Optional


from helpers.utils.filters import first_index_after


try:
    from patterns.analise import run_full_analysis, AnalysisResult
except ImportError:
    from roulette_analyzer import run_full_analysis, AnalysisResult



from datetime import datetime

import threading

import time 

from datetime import datetime



import requests
from typing import List, Dict, Tuple, Optional
import logging

logger = logging.getLogger(__name__)

BET_API_URL = "http://localhost:3000/api/bet"


# ══════════════════════════════════════════════════════════════════════════
# ESTADO GLOBAL POR ROLETA
# ══════════════════════════════════════════════════════════════════════════

class RouletteState:
    """Estado de monitoramento de uma roleta"""
    def __init__(self):
        self.last_analysis_count: int = 0
        self.current_analysis: Optional[AnalysisResult] = None
        self.is_monitoring: bool = False


# Armazena estado de cada roleta
_states: Dict[str, RouletteState] = {}


def _get_state(slug: str) -> RouletteState:
    """Obtém ou cria estado para uma roleta"""
    if slug not in _states:
        _states[slug] = RouletteState()
    return _states[slug]


# ══════════════════════════════════════════════════════════════════════════
# CONFIGURAÇÕES
# ══════════════════════════════════════════════════════════════════════════

ANALYSIS_INTERVAL = 30          # Refaz análise a cada N números
MIN_NUMBERS = 50                # Mínimo de números para análise
SAMPLE_SIZE = 150               # Quantidade de números para análise
MIN_CONFIDENCE_SCORE = 70       # Score mínimo para gerar sinal



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

# ══════════════════════════════════════════════════════════════════════════
# FUNÇÃO PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════

def process_roulette(roulette, numbers: List[int], full_results: List[Dict] = None) -> Optional[Dict]:
    """
    Processa números da roleta e retorna sinal se gatilho for ativado.
    
    Args:
        roulette: Dict com slug, name, url da roleta
        numbers: Lista de números (mais recente primeiro)
        full_results: Lista completa de resultados (opcional)
    
    Returns:
        Dict com sinal se gatilho ativado, None caso contrário
    """
    
    if len(numbers) < MIN_NUMBERS:
        return None

    
    
    slug = roulette['slug']
    state = _get_state(slug)
    last_number = numbers[0]

    print(last_number, slug)
    
    # ══════════════════════════════════════════════════════════════════
    # VERIFICAR SE DEVE FAZER NOVA ANÁLISE
    # ══════════════════════════════════════════════════════════════════
    
    should_analyze = False
    
    # Primeira análise
    if state.current_analysis is None:
        should_analyze = True
    # Análise periódica a cada N números
    elif len(numbers) - state.last_analysis_count >= ANALYSIS_INTERVAL:
        should_analyze = True
    
    # ══════════════════════════════════════════════════════════════════
    # EXECUTAR ANÁLISE SE NECESSÁRIO
    # ══════════════════════════════════════════════════════════════════
    
    if should_analyze:
        try:
            numbers_to_analyze = numbers[:SAMPLE_SIZE]
            analysis = run_full_analysis(numbers_to_analyze)
            
            state.current_analysis = analysis
            state.last_analysis_count = len(numbers)
            state.is_monitoring = True
            
            
        except Exception as e:
            return None
    
    # ══════════════════════════════════════════════════════════════════
    # VERIFICAR SE O ÚLTIMO NÚMERO É UM GATILHO
    # ══════════════════════════════════════════════════════════════════
    
    if not state.is_monitoring or state.current_analysis is None:
        return None
    
    analysis = state.current_analysis
    
    # Verificar score mínimo
    if analysis.confidence_score < MIN_CONFIDENCE_SCORE:
        return None
    
    # Verificar se é gatilho
    trigger_type = None
    
    if last_number in analysis.main_triggers:
        trigger_type = 'main'

        triggers_set = set(analysis.main_triggers) | set(analysis.secondary_triggers)

        indice_atual = first_index_after(numbers, last_number, 1)
        ocorrencia = 1

        relatorio_puxada = {
            1: False,
            2: False,
            3: False,
        }

        while indice_atual is not None and ocorrencia <= 3:
            if indice_atual >= 3:
                anteriores = numbers[indice_atual - 4 : indice_atual - 1]
                if set(anteriores) & triggers_set:
                    relatorio_puxada[ocorrencia] = True

            indice_atual = first_index_after(numbers, last_number, indice_atual + 1)
            ocorrencia += 1

        
    
    if last_number in analysis.secondary_triggers:
        trigger_type = 'secondary'


        triggers_set = set(analysis.main_triggers) | set(analysis.secondary_triggers)

        indice_atual = first_index_after(numbers, last_number, 1)
        ocorrencia = 1

        relatorio_puxada = {
            1: False,
            2: False,
            3: False,
        }

        while indice_atual is not None and ocorrencia <= 3:
            if indice_atual >= 3:
                anteriores = numbers[indice_atual - 4 : indice_atual - 1]
                if set(anteriores) & triggers_set:
                    relatorio_puxada[ocorrencia] = True

            indice_atual = first_index_after(numbers, last_number, indice_atual + 1)
            ocorrencia += 1

    
    if trigger_type is None:
        
        bets = analysis.final_group.copy()

        ultimos_3 = numbers[1:3] if len(numbers) > 3 else numbers[1:]
        numeros_em_comum_bet = set(ultimos_3) & set(bets)

        if len(numeros_em_comum_bet) == 0 :
            dt = datetime.now()
            created_at = int(dt.timestamp())

            ultimos_10 = numbers[1:5] if len(numbers) > 10 else numbers[1:]

            pagou_antes = set(ultimos_10) & set([*analysis.main_triggers, *analysis.secondary_triggers])

            bets1 = [*analysis.main_triggers, *analysis.secondary_triggers]

        
            if 0 not in bets1:
                bets = [0] + bets1
                bets.sort()

            if pagou_antes :
                return None
           
            dt = datetime.now()
            created_at = int(dt.timestamp())
            
            signal = {
                "roulette_id": roulette['slug'],
                "roulette_name": roulette["name"],
                "roulette_url": roulette["url"],
                "pattern": f"NUMEROS_PUXANDO_GATILHO-{len(numeros_em_comum_bet)}",
                "triggers": last_number,
                "targets": bets1,
                "bets": bets1,
                "passed_spins": 0,
                "spins_required": 0,
                "spins_count": 0,
                "gales": 20,
                "score": analysis.confidence_score,
                "snapshot": numbers[:500],
                "status": "processing",
                "message": f"Gatilho {trigger_type}: {last_number} | Grupo: {len(bets)} números",
                "tags": [
                    f"trigger_{trigger_type}",
                    f"score_{int(analysis.confidence_score)}",
                    f"group_size_{len(bets)}"
                ],
                "temp_state": {
                    "trigger_type": trigger_type,
                    "trigger_number": last_number,
                    "main_triggers": analysis.main_triggers,
                    "secondary_triggers": analysis.secondary_triggers,
                    "methodology": {
                        "frequency": analysis.methodology.frequency[:4],
                        "anchors": analysis.methodology.anchors[:3],
                        "chains": analysis.methodology.chains[:3],
                        "terminals": analysis.methodology.terminals,
                        "zero_pattern": analysis.methodology.zero_pattern[:3]
                    }
                },
                "created_at": created_at,
                "timestamp": created_at
            }
            #return signal
        
        
        return None
    
    # ══════════════════════════════════════════════════════════════════
    # PREPARAR GRUPO DE APOSTAS (ZERO OBRIGATÓRIO)
    # ══════════════════════════════════════════════════════════════════
    
    bets = analysis.final_group.copy()
    if 0 not in bets:
        bets = [0] + bets
        bets.sort()
    
    # ══════════════════════════════════════════════════════════════════
    # VALIDAR: NENHUM NÚMERO DA APOSTA NOS ÚLTIMOS 3 ANTES DO GATILHO
    # ══════════════════════════════════════════════════════════════════
    
    # numbers[0] é o gatilho, numbers[1:4] são os 3 anteriores
    ultimos_3 = numbers[1:8] if len(numbers) > 3 else numbers[1:]
    
    # Verificar se algum dos últimos 3 está no grupo de apostas
    numeros_em_comum = set(ultimos_3) & set(bets)
    
    if numeros_em_comum:
        
        return None
    
    # ══════════════════════════════════════════════════════════════════
    # GATILHO ATIVADO - GERAR SINAL
    # ══════════════════════════════════════════════════════════════════
    
    print(f"[NUMEROS_PUXANDO] {slug} - 🎯 GATILHO {trigger_type.upper()}: {last_number}")
    print(f"  Grupo para apostar: {bets}")
    


    bets1 = [*analysis.main_triggers, *analysis.secondary_triggers]

    historico = (
        int(relatorio_puxada[1]),
        int(relatorio_puxada[2]),
        int(relatorio_puxada[3]),
        )

    PADROES = {
        (1, 0, 0): ("quente", True),
        (0, 1, 0): ("quente", True),
        (1, 1, 0): ("aquecendo", True),
        (0, 1, 1): ("aquecendo", False),
        (1, 0, 1): ("instavel", False),   # se quiser barrar, mude para False
        (0, 0, 1): ("frio", False),
        (0, 0, 0): ("morto", False),
        (1, 1, 1): ("saturado", False),
    }

    dt = datetime.now()
    created_at = int(dt.timestamp())
    
    signal = {
        "roulette_id": roulette['slug'],
        "roulette_name": roulette["name"],
        "roulette_url": roulette["url"],
        "pattern": f"NUMEROS_PUXANDO_{trigger_type.upper()}",
        "triggers": last_number,
        "targets": bets,
        "bets": bets,
        "passed_spins": 0,
        "spins_required": 0,
        "spins_count": 0,
        "gales": 4,
        "score": 0,
        "snapshot": numbers[:SAMPLE_SIZE],
        "status": "processing",
        "message": f"Gatilho {trigger_type}: {last_number} | Grupo: {len(bets)} números",
        "tags": [
            f"trigger_{trigger_type}",
            f"score_{int(analysis.confidence_score)}",
            f"group_size_{len(bets)}"
        ],
        "temp_state": {
            "activation" : 0,
            "trigger_type": trigger_type,
            "trigger_number": last_number,
            "main_triggers": analysis.main_triggers,
            "secondary_triggers": analysis.secondary_triggers,
            "methodology": {
                "frequency": analysis.methodology.frequency[:4],
                "anchors": analysis.methodology.anchors[:3],
                "chains": analysis.methodology.chains[:3],
                "terminals": analysis.methodology.terminals,
                "zero_pattern": analysis.methodology.zero_pattern[:3]
            }
        },
        "created_at": created_at,
        "timestamp": created_at
    }
    
    #_fire_bet_async(signal)
    return signal


# ══════════════════════════════════════════════════════════════════════════
# FUNÇÕES AUXILIARES
# ══════════════════════════════════════════════════════════════════════════

def get_status(slug: str) -> Dict:
    """Retorna status de monitoramento de uma roleta"""
    state = _get_state(slug)
    
    return {
        'roulette': slug,
        'is_monitoring': state.is_monitoring,
        'last_analysis_count': state.last_analysis_count,
        'has_analysis': state.current_analysis is not None,
        'group': state.current_analysis.final_group if state.current_analysis else None,
        'main_triggers': state.current_analysis.main_triggers if state.current_analysis else None,
        'secondary_triggers': state.current_analysis.secondary_triggers if state.current_analysis else None,
        'confidence_score': state.current_analysis.confidence_score if state.current_analysis else None
    }


def reset(slug: str = None):
    """Reseta estado de uma ou todas as roletas"""
    global _states
    if slug:
        if slug in _states:
            del _states[slug]
    else:
        _states.clear()
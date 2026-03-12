import threading

import time 

from datetime import datetime


from patterns.score_v4 import RouletteAnalyzer


import requests
from typing import List, Dict, Tuple, Optional
import logging

logger = logging.getLogger(__name__)

BET_API_URL = "http://localhost:3000/api/bet"


# ══════════════════════════════════════════════════════════════════════════
# CONFIGURAÇÃO DO SISTEMA DE TENDÊNCIA ("SURFAR A ONDA")
# ══════════════════════════════════════════════════════════════════════════

# Quantos sinais recentes analisar por mesa
JANELA_ANALISE = 5

# Assertividade mínima para entrar em processing (0-100)
ASSERTIVIDADE_MINIMA = 20.0

# Status que contam como WIN para o cálculo
STATUS_WIN = ['win', 'monitoring_win']

# Status que contam como LOSS para o cálculo  
STATUS_LOSS = ['lost', 'monitoring_lost']

# Status finalizados (para buscar histórico)
STATUS_FINALIZADOS = STATUS_WIN + STATUS_LOSS

FILTROS_PADRAO = {
    0: {'min': 55, 'max': 75},
    1: {'min': 40, 'max': 50},
    2: {'min': 65, 'max': 75},
    3: {'min': 70, 'max': 100},
    4: {'min': 60, 'max': 70},
    5: {'min': 55, 'max': 70},
    6: {'min': 75, 'max': 100},
}

def deve_entrar(pattern, score):
    """Verifica se deve entrar no sinal"""
    if pattern not in FILTROS_PADRAO:
        return score >= 60
    
    filtro = FILTROS_PADRAO[pattern]
    return filtro['min'] <= score < filtro['max']


# ══════════════════════════════════════════════════════════════════════════
# FUNÇÃO DE APOSTA VIA API (FIRE AND FORGET)
# ══════════════════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════════════════
# SISTEMA DE ANÁLISE DE TENDÊNCIA DA MESA
# ══════════════════════════════════════════════════════════════════════════

def calcular_assertividade_mesa(sinais: List[Dict]) -> Tuple[float, Dict]:
    """
    Calcula a assertividade baseada nos sinais recentes.
    
    Args:
        sinais: Lista de sinais finalizados (mais recente primeiro)
        
    Returns:
        (assertividade em %, detalhes do cálculo)
    """
    if not sinais:
        return 50.0, {
            'wins': 0,
            'losses': 0,
            'total': 0,
            'sequencia': [],
            'motivo': 'sem_dados'
        }
    
    wins = 0
    losses = 0
    sequencia = []
    
    for s in sinais:
        status = s.get('status', '')
        if status in STATUS_WIN:
            wins += 1
            sequencia.append('W')
        elif status in STATUS_LOSS:
            losses += 1
            sequencia.append('L')
    
    total = wins + losses
    
    if total == 0:
        return 50.0, {
            'wins': 0,
            'losses': 0,
            'total': 0,
            'sequencia': sequencia,
            'motivo': 'sem_resultados'
        }
    
    assertividade = (wins / total) * 100
    
    # Análise de tendência recente (últimos 3)
    tendencia_recente = sequencia[:3] if len(sequencia) >= 3 else sequencia
    losses_recentes = tendencia_recente.count('L')
    
    # Penalidade se últimos 3 são losses (mesa fria)
    if losses_recentes >= 3:
        assertividade = max(0, assertividade - 15)
    elif losses_recentes >= 2:
        assertividade = max(0, assertividade - 5)
    
    return assertividade, {
        'wins': wins,
        'losses': losses,
        'total': total,
        'sequencia': sequencia,
        'tendencia_recente': tendencia_recente,
        'losses_recentes': losses_recentes,
    }


def decidir_status_por_tendencia(
    roulette_id: str, 
    roulette_name: str,
    sinais_recentes: List[Dict],
    assertividade_minima: float = ASSERTIVIDADE_MINIMA
) -> Tuple[str, float, Dict]:
    """
    Decide se o sinal deve ser 'processing' ou 'monitoring' baseado na tendência da mesa.
    
    Args:
        roulette_id: ID da roleta
        roulette_name: Nome da roleta
        sinais_recentes: Lista de sinais recentes já buscados
        assertividade_minima: Threshold mínimo para entrar em processing
        
    Returns:
        (status, assertividade, detalhes)
    """
    assertividade, detalhes = calcular_assertividade_mesa(sinais_recentes)
    
    deve_processar = assertividade >= assertividade_minima
    
    detalhes['assertividade'] = round(assertividade, 1)
    detalhes['threshold'] = assertividade_minima
    detalhes['janela'] = len(sinais_recentes)
    detalhes['decisao'] = 'processing' if deve_processar else 'monitoring'
    
    status = 'processing' if deve_processar else 'monitoring'
    
    emoji = "🟢" if deve_processar else "👁️"
    print(
        f"[TENDENCIA] {emoji} Mesa {roulette_name}: "
        f"Assertividade {assertividade:.1f}% "
        f"({detalhes['wins']}W/{detalhes['losses']}L) "
        f"→ {status.upper()}"
    )
    
    return status, assertividade, detalhes


def process_roulette(roulette, historico, full_results, sinais_recentes: List[Dict] = None) :
    """
    Processa roleta e cria sinal se condições forem atendidas.
    
    Args:
        roulette: Dados da roleta
        historico: Lista de números históricos
        full_results: Resultados completos da API
        sinais_recentes: Lista de sinais recentes da mesa (para análise de tendência)
                        Se None, sempre cria como 'processing'
    
    Returns:
        Signal dict ou None
    """

    if len(historico) <= 200:
        return None

    analyzer = RouletteAnalyzer(historico)

    
    # Último número que saiu
    base = historico[0]


    analise = analyzer.analisar_completo(base, quantidade=13)

    confianca = analise['confianca']


    bet = sorted(analise['previsao'])

    tem_comum = bool(set(historico[1:5]) & set(bet))

    qtd_em_comum = len(set(historico[1:10]) & set(bet))



    iso_str = full_results[0]["timestamp_br"]
    dt = datetime.fromisoformat(iso_str)
    created_at = int(dt.timestamp())

    if deve_entrar(qtd_em_comum, confianca) :
        if 0 in bet :
            bet.pop()
        else :
            bet.insert(0,0)
            bet.pop()
        
        # ══════════════════════════════════════════════════════════════════
        # DECISÃO DE STATUS BASEADA NA TENDÊNCIA DA MESA
        # ══════════════════════════════════════════════════════════════════
        status = "processing"  # Default
        tendencia_info = None
        message = "Gatilho encontrado!"
        
        if sinais_recentes is not None:
            status, assertividade, tendencia_info = decidir_status_por_tendencia(
                roulette_id=roulette['slug'],
                roulette_name=roulette['name'],
                sinais_recentes=sinais_recentes,
                assertividade_minima=ASSERTIVIDADE_MINIMA
            )
            
            if status == "monitoring":
                message = f"👁️ MONITORING - Mesa com {assertividade:.1f}% assertividade ({tendencia_info['wins']}W/{tendencia_info['losses']}L)"
            else:
                message = f"🟢 Gatilho encontrado! Mesa com {assertividade:.1f}% assertividade"


        signal = {
            "roulette_id": roulette['slug'],
            "roulette_name" : roulette["name"],
            "roulette_url" : roulette["url"],
            "pattern" : f"SCORE-{qtd_em_comum}",
            "triggers": historico[0],
            "targets":[*bet],
            "bets": bet,
            "passed_spins" : 0,
            "spins_required" : 0,
            "spins_count": 0,
            "gales" : 3,
            "score" : confianca,
            "snapshot":historico[:200],
            "status": status,
            "message" : message,
            "tags" : [],
            "temp_state" : {
                "tendencia_mesa": tendencia_info
            } if tendencia_info else None,
            "created_at" : created_at,
            "timestamp" : created_at
        }


        
        # ══════════════════════════════════════════════════════════════════
        # DISPARA APOSTA VIA API (FIRE AND FORGET) - SÓ SE FOR PROCESSING
        # ══════════════════════════════════════════════════════════════════
        #if status == "processing":
            #_fire_bet_async(signal)
        
        return signal
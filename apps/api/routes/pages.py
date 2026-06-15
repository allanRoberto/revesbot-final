from __future__ import annotations

import os

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from api.core.config import settings
from api.helpers.roulettes_list import roulettes


router = APIRouter()
base_dir = os.path.dirname(os.path.dirname(__file__))
templates_dir = os.path.join(base_dir, "templates")


@router.get("/", response_class=HTMLResponse)
async def dashboard():
    with open(os.path.join(templates_dir, "dashboard.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/analise", response_class=HTMLResponse)
async def analise_page():
    """
    Página principal de análise de números
    """
    with open(os.path.join(templates_dir, "analise.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/assertividade", response_class=HTMLResponse)
async def assertividade():
    with open(os.path.join(templates_dir, "assertividade.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/assertiveness-replay", response_class=HTMLResponse)
async def assertiveness_replay_page():
    with open(os.path.join(templates_dir, "assertiveness_replay.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/occurrences-lab", response_class=HTMLResponse)
async def occurrences_lab_page():
    with open(os.path.join(templates_dir, "occurrences_lab.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/next-number-rankings", response_class=HTMLResponse)
async def next_number_rankings_page():
    with open(os.path.join(templates_dir, "next_number_rankings.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/next-number-rankings/backtest", response_class=HTMLResponse)
async def next_number_rankings_backtest_page():
    with open(os.path.join(templates_dir, "next_number_backtest.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/next-number-sequences", response_class=HTMLResponse)
async def next_number_sequences_page():
    with open(os.path.join(templates_dir, "next_number_sequences.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/occurrences-runs", response_class=HTMLResponse)
@router.get("/occurrences-live-runs", response_class=HTMLResponse)
async def occurrences_runs_page():
    with open(os.path.join(templates_dir, "occurrences_live_runs.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/occurrences-runs/{run_id}", response_class=HTMLResponse)
async def occurrence_run_detail_page(run_id: str):
    with open(os.path.join(templates_dir, "occurrences_run_detail.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/analizador", response_class=HTMLResponse)
async def analizador_page():
    """
    Página do Analizador Master + Estelar + Puxadas
    """
    with open(os.path.join(templates_dir, "analizador.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/sugestao", response_class=HTMLResponse)
async def sugestao_page():
    """
    Página do Analizador Master + Estelar + Puxadas
    """
    with open(os.path.join(templates_dir, "sugestao.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/agent", response_class=HTMLResponse)
async def agent_page():
    """
    Página do Agente de padrões
    """
    with open(os.path.join(templates_dir, "agent.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/agent/sessions", response_class=HTMLResponse)
async def agent_sessions_page():
    """
    Página de sessões do agente
    """
    with open(os.path.join(templates_dir, "agent_sessions.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/agent/templates", response_class=HTMLResponse)
async def agent_templates_page():
    """
    Página de templates do agente
    """
    with open(os.path.join(templates_dir, "agent_templates.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/monitor", response_class=HTMLResponse)
async def monitor_page(request: Request):
    """
    Página de monitoramento de apostas em tempo real
    """
    templates = Jinja2Templates(directory=templates_dir)
    return templates.TemplateResponse(
        "monitor.html",
        {"request": request}
    )


@router.get("/suggestion-monitor", response_class=HTMLResponse)
async def suggestion_monitor_dashboard_page():
    with open(os.path.join(templates_dir, "suggestion_monitor_dashboard.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/suggestion-rank-timeline", response_class=HTMLResponse)
async def suggestion_rank_timeline_page(request: Request):
    templates = Jinja2Templates(directory=templates_dir)
    roulette_url_map = {
        str(item.get("slug") or "").strip(): str(item.get("url") or "").strip()
        for item in roulettes
        if str(item.get("slug") or "").strip()
    }
    return templates.TemplateResponse(
        "suggestion_rank_timeline.html",
        {
            "request": request,
            "bot_automation_enabled": bool(settings.bot_automation_enabled),
            "bot_api_url": settings.bot_api_url,
            "roulette_url_map": roulette_url_map,
        },
    )


@router.get("/pattern-training", response_class=HTMLResponse)
async def pattern_training_page():
    with open(os.path.join(templates_dir, "pattern_training.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/pattern-score-training", response_class=HTMLResponse)
async def pattern_score_training_page():
    with open(os.path.join(templates_dir, "pattern_score_training.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/decoder-lab", response_class=HTMLResponse)
async def decoder_lab_page():
    with open(os.path.join(templates_dir, "decoder_lab.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/decoder-monitor", response_class=HTMLResponse)
async def decoder_monitor_page():
    with open(os.path.join(templates_dir, "decoder_monitor.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/ai-shadow-monitor", response_class=HTMLResponse)
async def ai_shadow_monitor_page():
    with open(os.path.join(templates_dir, "ai_shadow_monitor.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/triplet-lookup", response_class=HTMLResponse)
async def triplet_lookup_page():
    with open(os.path.join(templates_dir, "triplet_lookup.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/triplet-strategy", response_class=HTMLResponse)
async def triplet_strategy_list_page():
    with open(os.path.join(templates_dir, "triplet_strategy_list.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/triplet-strategy/{roulette_id}", response_class=HTMLResponse)
async def triplet_strategy_detail_page(roulette_id: str):
    with open(os.path.join(templates_dir, "triplet_strategy_detail.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/puxado-triggers", response_class=HTMLResponse)
async def puxado_triggers_page():
    with open(os.path.join(templates_dir, "puxado_triggers.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/gatilhos", response_class=HTMLResponse)
async def gatilhos_page():
    with open(os.path.join(templates_dir, "gatilhos.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/configuracoes", response_class=HTMLResponse)
async def configuracoes_page():
    with open(os.path.join(templates_dir, "configuracoes.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/sinais-v2", response_class=HTMLResponse)
async def sinais_v2_page():
    with open(os.path.join(templates_dir, "sinais_v2.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/ranking-trios", response_class=HTMLResponse)
async def triplet_ranking_page():
    with open(os.path.join(templates_dir, "triplet_ranking.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/trio-ranking-sinais", response_class=HTMLResponse)
async def trio_ranking_signals_page():
    with open(os.path.join(templates_dir, "trio_ranking_signals.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/pattern-assertiveness", response_class=HTMLResponse)
async def pattern_assertiveness_page():
    with open(os.path.join(templates_dir, "pattern_assertiveness.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/validar-padrao", response_class=HTMLResponse)
async def triplet_pattern_page():
    with open(os.path.join(templates_dir, "triplet_pattern.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/buscar-sequencia", response_class=HTMLResponse)
async def sequence_search_page():
    with open(os.path.join(templates_dir, "sequence_search.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/previsao-setores", response_class=HTMLResponse)
async def previsao_setores_page():
    with open(os.path.join(templates_dir, "previsao_setores_backtest.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/validar-padrao-ocorrencia", response_class=HTMLResponse)
async def occurrence_signal_page():
    with open(os.path.join(templates_dir, "occurrence_signal.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/sinais-ocorrencia", response_class=HTMLResponse)
async def occurrence_signal_signals_page():
    with open(os.path.join(templates_dir, "occurrence_signal_signals.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/sinais-terminal-7", response_class=HTMLResponse)
async def terminal_7_signal_signals_page():
    with open(os.path.join(templates_dir, "terminal_7_signal_signals.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/sinais-confluencia-terminal", response_class=HTMLResponse)
async def triplet_terminal_signals_page():
    with open(os.path.join(templates_dir, "triplet_terminal_signals.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/sinais-confluencia-terminal-4", response_class=HTMLResponse)
async def quadruplet_terminal_signals_page():
    with open(os.path.join(templates_dir, "quadruplet_terminal_signals.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/sinais-confluencia-terminal-5", response_class=HTMLResponse)
async def quintet_terminal_signals_page():
    with open(os.path.join(templates_dir, "quintet_terminal_signals.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/sinais-quintet-shuffled", response_class=HTMLResponse)
async def quintet_shuffled_signals_page():
    with open(os.path.join(templates_dir, "quintet_shuffled_signals.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/sinais-t8t9", response_class=HTMLResponse)
async def t8t9_signals_page():
    with open(os.path.join(templates_dir, "t8t9_signals.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/numeros-fortes-signals", response_class=HTMLResponse)
async def numeros_fortes_signals_page():
    with open(os.path.join(templates_dir, "numeros_fortes_signals.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/numeros-fortes-inversao-signals", response_class=HTMLResponse)
async def numeros_fortes_inversao_signals_page():
    with open(os.path.join(templates_dir, "numeros_fortes_inversao_signals.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/sinais-hidra", response_class=HTMLResponse)
async def hidra_signals_page():
    with open(os.path.join(templates_dir, "hidra_signals.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/sinais-ensemble", response_class=HTMLResponse)
async def ensemble_signals_page():
    with open(os.path.join(templates_dir, "ensemble_signals.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/sinais-puxados", response_class=HTMLResponse)
async def puxados_signals_page():
    with open(os.path.join(templates_dir, "puxados_signals.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/analise-puxadas", response_class=HTMLResponse)
async def analise_puxadas_page():
    """Ferramenta visual de análise manual de puxadas / ocorrências."""
    with open(os.path.join(templates_dir, "analise_puxadas.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/sinais-puxadas-inversao", response_class=HTMLResponse)
async def puxadas_inversao_signals_page():
    """Dashboard de assertividade — Puxadas Inversão (trigger = inversão pagou)."""
    with open(os.path.join(templates_dir, "puxadas_inversao_signals.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/sinais-puxadas", response_class=HTMLResponse)
async def puxadas_sinal_signals_page():
    """Dashboard de assertividade — Puxadas (inversão como parâmetro)."""
    with open(os.path.join(templates_dir, "puxadas_sinal_signals.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/multi-pivo", response_class=HTMLResponse)
async def multi_pivo_page():
    """Análise multi-pivô: contexto que cerca os 5 últimos números sorteados."""
    with open(os.path.join(templates_dir, "multi_pivo.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/sinais-multi-pivo", response_class=HTMLResponse)
async def multi_pivo_signals_page():
    """Dashboard de assertividade — Sinais Multi-Pivô."""
    with open(os.path.join(templates_dir, "multi_pivo_signals.html"), "r", encoding="utf-8") as f:
        return f.read()


@router.get("/autoroulette", response_class=HTMLResponse)
async def autoroulette_page():
    with open(os.path.join(templates_dir, "autoroulette.html"), "r", encoding="utf-8") as f:
        return f.read()

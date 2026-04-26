from __future__ import annotations

import os

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


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

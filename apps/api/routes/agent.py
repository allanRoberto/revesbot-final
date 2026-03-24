from __future__ import annotations

import asyncio
import logging
import json
import os
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

import pytz
from fastapi import APIRouter, HTTPException, Query, Body
from pydantic import BaseModel, Field

from api.core.db import agent_sessions_coll, agent_templates_coll, history_coll
from api.helpers.roulettes_list import roulettes

from openai import OpenAI
try:
    from anthropic import Anthropic
except Exception:  # pragma: no cover - optional dependency
    Anthropic = None


router = APIRouter()
logger = logging.getLogger("agent")

SESSION_KEY_PREFIX = "agent:session:"
MAX_MESSAGES = 200
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower()
_raw_models = os.getenv("LLM_MODELS", "")
if _raw_models.strip():
    DEFAULT_MODELS = [m.strip() for m in _raw_models.split(",") if m.strip()]
else:
    if LLM_PROVIDER == "anthropic":
        DEFAULT_MODELS = [
            "claude-opus-4-1-20250805",
            "claude-opus-4-20250514",
            "claude-sonnet-4-20250514",
            "claude-3-7-sonnet-20250219",
            "claude-3-7-sonnet-latest",
            "claude-3-5-haiku-20241022",
            "claude-3-5-haiku-latest",
            "claude-3-haiku-20240307",
        ]
    else:
        DEFAULT_MODELS = [
            "gpt-5",
            "gpt-4.1",
            "gpt-4o",
            "gpt-4o-mini",
        ]

openai_client = OpenAI()
anthropic_client = Anthropic() if LLM_PROVIDER == "anthropic" and Anthropic else None
roulette_lookup = {r["slug"]: r for r in roulettes}

DEFAULT_PRICING = {
    # OpenAI (USD per 1M tokens)
    "gpt-5": {"input": 1.25, "output": 10.0},
    "gpt-4.1": {"input": 2.0, "output": 8.0},
    "gpt-4o": {"input": 2.5, "output": 10.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.6},
    "gpt-4.1-mini": {"input": 0.4, "output": 1.6},
    # Anthropic (USD per 1M tokens)
    "claude-opus-4-1-20250805": {"input": 15.0, "output": 75.0},
    "claude-opus-4-20250514": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
    "claude-3-7-sonnet-20250219": {"input": 3.0, "output": 15.0},
    "claude-3-7-sonnet-latest": {"input": 3.0, "output": 15.0},
    "claude-3-5-haiku-20241022": {"input": 0.8, "output": 4.0},
    "claude-3-5-haiku-latest": {"input": 0.8, "output": 4.0},
    "claude-3-haiku-20240307": {"input": 0.25, "output": 1.25},
}

_pricing_raw = os.getenv("LLM_PRICING", "")
try:
    env_pricing = json.loads(_pricing_raw) if _pricing_raw else {}
except Exception:
    env_pricing = {}
MODEL_PRICING = {**DEFAULT_PRICING, **env_pricing}


class AgentStateIn(BaseModel):
    session_id: str
    roulette_id: Optional[str] = None
    fixed_rules: str = ""
    instructions: str = ""
    model: Optional[str] = None
    use_history: Optional[bool] = None
    history_limit: Optional[int] = None
    recent_numbers: Optional[List[int]] = None
    template_id: Optional[str] = None
    template_prompt: Optional[str] = None
    template_output_mode: Optional[str] = None
    session_rules: Optional[List[Dict[str, Any]]] = None
    messages: List[Dict[str, Any]] = Field(default_factory=list)


class AgentMessageIn(BaseModel):
    session_id: str
    text: str
    roulette_id: Optional[str] = None
    fixed_rules: Optional[str] = None
    model: Optional[str] = None
    use_history: Optional[bool] = None
    history_limit: Optional[int] = None
    template_id: Optional[str] = None
    template_prompt: Optional[str] = None
    template_output_mode: Optional[str] = None
    session_rules: Optional[List[Dict[str, Any]]] = None


class AgentSessionIn(BaseModel):
    model: Optional[str] = None


class AgentCloneIn(BaseModel):
    session_id: str


class AgentPredictionIn(BaseModel):
    roulette_id: str
    history: List[int]
    stats: Optional[Dict[str, Any]] = None
    suggestion_base: Optional[List[int]] = None
    suggestion_extended: Optional[List[int]] = None
    tooltip_number: Optional[int] = None
    tooltip_data: Optional[Dict[str, Any]] = None
    model: Optional[str] = None


class AgentTemplateIn(BaseModel):
    name: str
    prompt: str
    rules: Optional[List[Dict[str, Any]]] = None
    output_mode: Optional[str] = None


def _session_key(session_id: str) -> str:
    return f"{SESSION_KEY_PREFIX}{session_id}"


def _default_state(session_id: str, model: Optional[str] = None) -> Dict[str, Any]:
    return {
        "session_id": session_id,
        "roulette_id": None,
        "fixed_rules": "",
        "instructions": "",
        "model": _normalize_model(model),
        "use_history": False,
        "history_limit": 50,
        "recent_numbers": [],
        "template_id": None,
        "template_prompt": "",
        "template_output_mode": "text",
        "compact_prompt": "",
        "session_rules": [],
        "messages": [],
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }


async def _load_state(session_id: str) -> Dict[str, Any]:
    doc = await agent_sessions_coll.find_one({"session_id": session_id})
    if not doc:
        return _default_state(session_id)
    doc.pop("_id", None)
    return doc


def _serialize_state(state: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(state.get("created_at"), datetime):
        state["created_at"] = state["created_at"].isoformat()
    if isinstance(state.get("updated_at"), datetime):
        state["updated_at"] = state["updated_at"].isoformat()
    return state


def _roulette_stats(numbers: List[int]) -> Dict[str, Any]:
    if not numbers:
        return {}

    total = len(numbers)
    reds = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}

    def pct(count: int) -> float:
        return round((count / total) * 100, 2) if total else 0.0

    dozens = {1: 0, 2: 0, 3: 0}
    columns = {1: 0, 2: 0, 3: 0}
    parity = {"par": 0, "impar": 0, "zero": 0}
    colors = {"vermelho": 0, "preto": 0, "verde": 0}
    terminals = {str(i): 0 for i in range(10)}
    freq: Dict[int, int] = {}

    for n in numbers:
        freq[n] = freq.get(n, 0) + 1
        if n == 0:
            parity["zero"] += 1
            colors["verde"] += 1
            terminals["0"] += 1
            continue
        parity["par" if n % 2 == 0 else "impar"] += 1
        colors["vermelho" if n in reds else "preto"] += 1
        if 1 <= n <= 12:
            dozens[1] += 1
        elif 13 <= n <= 24:
            dozens[2] += 1
        elif 25 <= n <= 36:
            dozens[3] += 1
        columns[((n - 1) % 3) + 1] += 1
        terminals[str(n % 10)] += 1

    hot_numbers = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:6]
    cold_numbers = sorted(freq.items(), key=lambda x: x[1])[:6]
    repetitions = [n for n, c in freq.items() if c >= 2]

    cavalo_groups = {
        "147": [1, 4, 7, 11, 14, 17, 21, 24, 27, 31, 34],
        "369": [3, 6, 9, 13, 16, 19, 23, 26, 29, 33, 36],
        "258": [2, 5, 8, 12, 15, 18, 22, 25, 28, 32, 35],
        "036": [0, 3, 6, 10, 13, 16, 20, 23, 26, 30, 33, 36],
    }

    cavalos = {}
    for label, group in cavalo_groups.items():
        count = sum(1 for n in numbers if n in group)
        cavalos[label] = {"count": count, "percent": pct(count)}

    return {
        "total": total,
        "last_numbers": numbers[:10],
        "hot_numbers": hot_numbers,
        "cold_numbers": cold_numbers,
        "repetitions": repetitions[:10],
        "hot_terminals": sorted(terminals.items(), key=lambda x: x[1], reverse=True)[:3],
        "cold_terminals": sorted(terminals.items(), key=lambda x: x[1])[:3],
        "hot_cavalos": sorted(cavalos.items(), key=lambda x: x[1]["count"], reverse=True)[:2],
        "cold_cavalos": sorted(cavalos.items(), key=lambda x: x[1]["count"])[:2],
        "dozens": {k: {"count": v, "percent": pct(v)} for k, v in dozens.items()},
        "columns": {k: {"count": v, "percent": pct(v)} for k, v in columns.items()},
        "parity": {k: {"count": v, "percent": pct(v)} for k, v in parity.items()},
        "colors": {k: {"count": v, "percent": pct(v)} for k, v in colors.items()},
        "terminals": {k: {"count": v, "percent": pct(v)} for k, v in terminals.items()},
        "cavalos": cavalos,
        "hot_regions": sorted(dozens.items(), key=lambda x: x[1], reverse=True)[:2],
        "cold_regions": sorted(dozens.items(), key=lambda x: x[1])[:2],
    }


async def _fetch_recent_numbers(roulette_id: str, limit: int) -> List[int]:
    # Always newest-first: index 0 is the latest spin.
    cursor = (
        history_coll
        .find({"roulette_id": roulette_id})
        .sort("timestamp", -1)
        .limit(limit)
    )
    docs = await cursor.to_list(length=limit)
    return [doc["value"] for doc in docs]


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


async def _mcp_get_last_numbers(roulette_id: str, limit: int) -> Dict[str, Any]:
    numbers = await _fetch_recent_numbers(roulette_id, limit)
    return {
        "roulette_id": roulette_id,
        "limit": limit,
        "results": numbers,
        "order": "desc",
    }


async def _mcp_get_following_numbers(
    roulette_id: str,
    number: int,
    next_count: int = 3,
    occurrences: int = 4,
    lookback: int = 5000,
) -> Dict[str, Any]:
    numbers = await _fetch_recent_numbers(roulette_id, lookback)
    occurrences_data = []
    for idx, value in enumerate(numbers):
        if value != number:
            continue
        next_slice = numbers[max(0, idx - next_count):idx][::-1]
        occurrences_data.append({
            "occurrence_index": idx,
            "next_numbers": next_slice,
        })
        if len(occurrences_data) >= occurrences:
            break
    return {
        "roulette_id": roulette_id,
        "number": number,
        "next_count": next_count,
        "occurrences": occurrences,
        "found": len(occurrences_data),
        "results": occurrences_data,
    }


async def _mcp_get_stats(roulette_id: str, limit: int = 500) -> Dict[str, Any]:
    numbers = await _fetch_recent_numbers(roulette_id, limit)
    stats = _roulette_stats(numbers) if numbers else {}
    return {
        "roulette_id": roulette_id,
        "limit": limit,
        "stats": stats,
    }


async def _mcp_get_numbers_by_time_window(
    roulette_id: str,
    days: int,
    start_time: str,
    end_time: str,
) -> Dict[str, Any]:
    tz_br = pytz.timezone("America/Sao_Paulo")
    now_br = datetime.now(tz_br)
    start_date_br = now_br - timedelta(days=days)

    # Fetch a wider range in UTC and filter in Python by BR time window.
    start_utc = start_date_br.astimezone(pytz.utc)
    end_utc = now_br.astimezone(pytz.utc)

    cursor = (
        history_coll
        .find({"roulette_id": roulette_id, "timestamp": {"$gte": start_utc, "$lte": end_utc}})
        .sort("timestamp", -1)
    )
    docs = await cursor.to_list(length=200000)

    try:
        start_h, start_m = map(int, start_time.split(":"))
        end_h, end_m = map(int, end_time.split(":"))
    except Exception:
        raise HTTPException(status_code=400, detail="Horario invalido. Use HH:MM.")

    filtered = []
    for doc in docs:
        ts = doc.get("timestamp")
        if not ts:
            continue
        if ts.tzinfo is None:
            ts = pytz.utc.localize(ts)
        br_time = ts.astimezone(tz_br)
        start_dt = br_time.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
        end_dt = br_time.replace(hour=end_h, minute=end_m, second=59, microsecond=999999)
        if start_dt <= br_time <= end_dt:
            filtered.append({
                "value": doc.get("value"),
                "timestamp": ts.isoformat(),
                "timestamp_br": br_time.isoformat(),
            })

    return {
        "roulette_id": roulette_id,
        "days": days,
        "start_time": start_time,
        "end_time": end_time,
        "count": len(filtered),
        "results": filtered,
    }


def _normalize_model(model: Optional[str]) -> str:
    if not model:
        return DEFAULT_MODELS[0]
    if model in DEFAULT_MODELS:
        return model
    return DEFAULT_MODELS[0]


def _normalize_rules(rules: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    if not rules:
        return []
    normalized = []
    for idx, rule in enumerate(rules):
        if not isinstance(rule, dict):
            continue
        text = str(rule.get("text", "")).strip()
        if not text:
            continue
        normalized.append({
            "id": rule.get("id") or f"rule-{idx}",
            "text": text,
            "active": bool(rule.get("active", True)),
        })
    return normalized


def _normalize_output_mode(mode: Optional[str]) -> str:
    if not mode:
        return "text"
    mode = mode.strip().lower()
    return "json" if mode == "json" else "text"


def _estimate_cost(provider: str, model: str, usage: Dict[str, Any]) -> Optional[float]:
    pricing = MODEL_PRICING.get(model)
    if not pricing:
        return None
    input_tokens = usage.get("input_tokens") or 0
    output_tokens = usage.get("output_tokens") or 0
    input_cost = (input_tokens / 1_000_000) * float(pricing.get("input", 0))
    output_cost = (output_tokens / 1_000_000) * float(pricing.get("output", 0))
    return round(input_cost + output_cost, 6)


def _call_llm_sync(model: str, prompt: str) -> Dict[str, Any]:
    if LLM_PROVIDER == "anthropic":
        if not anthropic_client:
            raise RuntimeError("Anthropic client not available. Install 'anthropic' and set ANTHROPIC_API_KEY.")
        resp = anthropic_client.messages.create(
            model=model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        parts = []
        for block in getattr(resp, "content", []):
            if getattr(block, "type", "") == "text":
                parts.append(getattr(block, "text", ""))
        usage = {
            "input_tokens": getattr(resp.usage, "input_tokens", 0) if getattr(resp, "usage", None) else 0,
            "output_tokens": getattr(resp.usage, "output_tokens", 0) if getattr(resp, "usage", None) else 0,
        }
        return {"text": "\n".join(parts).strip(), "usage": usage}

    response = openai_client.responses.create(
        model=model,
        input=prompt,
    )
    usage = {
        "input_tokens": getattr(response.usage, "input_tokens", 0) if getattr(response, "usage", None) else 0,
        "output_tokens": getattr(response.usage, "output_tokens", 0) if getattr(response, "usage", None) else 0,
    }
    return {"text": (response.output_text or "").strip(), "usage": usage}


async def _save_state(state: Dict[str, Any]) -> None:
    if "messages" in state and isinstance(state["messages"], list):
        state["messages"] = state["messages"][-MAX_MESSAGES:]
    now = datetime.utcnow()
    state["updated_at"] = now
    state.pop("created_at", None)
    await agent_sessions_coll.update_one(
        {"session_id": state["session_id"]},
        {
            "$set": state,
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )


@router.post("/api/agent/session")
async def create_agent_session(payload: Optional[AgentSessionIn] = Body(default=None)) -> Dict[str, str]:
    session_id = str(uuid4())
    model = payload.model if payload else None
    await _save_state(_default_state(session_id, model=model))
    return {"session_id": session_id}


@router.get("/api/agent/state")
async def get_agent_state(session_id: str = Query(...)) -> Dict[str, Any]:
    state = await _load_state(session_id)
    return _serialize_state(state)


@router.post("/api/agent/state")
async def save_agent_state(payload: AgentStateIn) -> Dict[str, str]:
    state = payload.model_dump()
    state["model"] = _normalize_model(state.get("model"))
    state["session_rules"] = _normalize_rules(state.get("session_rules"))
    state["template_output_mode"] = _normalize_output_mode(state.get("template_output_mode"))
    state["updated_at"] = datetime.utcnow()
    await _save_state(state)
    return {"status": "ok"}


@router.post("/api/agent/message")
async def agent_message(payload: AgentMessageIn) -> Dict[str, Any]:
    print("[agent] /api/agent/message payload:", payload.model_dump())
    state = await _load_state(payload.session_id)
    model = _normalize_model(payload.model or state.get("model"))

    roulette_id = payload.roulette_id or state.get("roulette_id")
    fixed_rules = payload.fixed_rules if payload.fixed_rules is not None else state.get("fixed_rules", "")
    use_history = payload.use_history if payload.use_history is not None else state.get("use_history", False)
    history_limit = payload.history_limit or state.get("history_limit", 50)
    template_prompt = payload.template_prompt if payload.template_prompt is not None else state.get("template_prompt", "")
    template_output_mode = _normalize_output_mode(
        payload.template_output_mode if payload.template_output_mode is not None else state.get("template_output_mode")
    )
    session_rules = _normalize_rules(
        payload.session_rules if payload.session_rules is not None else state.get("session_rules", [])
    )

    numbers_context = ""
    stats_context = ""
    context_numbers: List[int] = []
    recent_numbers: List[int] = state.get("recent_numbers", []) or []
    user_text = payload.text.strip()

    normalized_text = _normalize_text(user_text)
    is_realtime_update = bool(re.match(r"^resultados?\s+em\s+tempo\s+real", normalized_text))
    history_limit_context = min(history_limit, 30) if is_realtime_update else history_limit
    match = re.search(r"analise\s+os\s+(\d+)\s+ultimos\s+numeros\b", normalized_text)
    if not match:
        match = re.search(r"analise\s+os\s+(\d+)\s+ultimos\s+numeros\W?", normalized_text)
    if match:
        history_limit = max(1, min(int(match.group(1)), 5000))
        history_limit_context = history_limit
        use_history = True

    tool_result = None
    tool_used = None
    if roulette_id:
        # If user asks what is in the current context, return the exact cached list.
        if re.search(r"(qual|quais)\s+lista.*contexto", normalized_text):
            tool_used = "context_recent_numbers"
            tool_result = {
                "roulette_id": roulette_id,
                "history_limit": history_limit,
                "use_history": use_history,
                "results": recent_numbers[:history_limit],
                "order": "desc",
            }

        match_last = re.search(
            r"(busque|buscar|mostre|traga|retorne)\s+os\s+(\d+)\s+ultimos\s+(numeros|resultados)",
            normalized_text,
        )
        if not match_last:
            match_last = re.search(
                r"(busque|buscar|mostre|traga|retorne)\s+os\s+ultimos\s+(\d+)\s+(numeros|resultados)",
                normalized_text,
            )
        if not match_last:
            match_last = re.search(
                r"(ultimos|ultimas)\s+(\d+)\s+(numeros|resultados)",
                normalized_text,
            )
        if not match_last:
            match_last = re.search(
                r"(\d+)\s+ultimos\s+(numeros|resultados)",
                normalized_text,
            )
        if match_last:
            if match_last.group(1).isdigit():
                limit = max(1, min(int(match_last.group(1)), 5000))
            else:
                limit = max(1, min(int(match_last.group(2)), 5000))
            tool_result = await _mcp_get_last_numbers(roulette_id, limit)
            tool_used = "get_last_numbers"
            recent_numbers = tool_result.get("results", recent_numbers)

        match_follow = re.search(
            r"(quais|mostre|liste)\s+numeros\s+o\s+numero\s+(\d+)\s+puxou\s+nas\s+(\d+)\s+rodadas\s+seguintes\s+nas\s+ultimas\s+(\d+)\s+ocorrencias",
            normalized_text,
        )
        if match_follow:
            number = int(match_follow.group(2))
            next_count = int(match_follow.group(3))
            occurrences = int(match_follow.group(4))
            tool_result = await _mcp_get_following_numbers(
                roulette_id,
                number,
                next_count=next_count,
                occurrences=occurrences,
            )
            tool_used = "get_following_numbers"

        match_stats = re.search(r"(estatisticas|stats)\s+da\s+roleta", normalized_text)
        if match_stats:
            tool_result = await _mcp_get_stats(roulette_id, limit=history_limit)
            tool_used = "get_roulette_stats"

        match_time = re.search(
            r"nos\s+(\d+)\s+dias\s+anteriores\s+no\s+horario\s+das\s+(\d{1,2}:\d{2})\s+as\s+(\d{1,2}:\d{2})",
            normalized_text,
        )
        if not match_time:
            match_time = re.search(
                r"nos\s+(\d+)\s+dias\s+anteriores\s+entre\s+(\d{1,2}:\d{2})\s+e\s+(\d{1,2}:\d{2})",
                normalized_text,
            )
        if match_time:
            days = int(match_time.group(1))
            start_time = match_time.group(2)
            end_time = match_time.group(3)
            tool_result = await _mcp_get_numbers_by_time_window(
                roulette_id,
                days=days,
                start_time=start_time,
                end_time=end_time,
            )
            tool_used = "get_numbers_by_time_window"

    force_history_fetch = bool(match) or tool_used in {
        "get_last_numbers",
        "get_following_numbers",
        "get_roulette_stats",
        "get_numbers_by_time_window",
    }

    if roulette_id:
        if use_history:
            try:
                if recent_numbers and not force_history_fetch:
                    # Prefer the cached list from the session (includes live WS updates).
                    numbers = recent_numbers[:history_limit_context]
                else:
                    numbers = await _fetch_recent_numbers(roulette_id, history_limit_context)
                if numbers:
                    if not (is_realtime_update and recent_numbers and not force_history_fetch):
                        recent_numbers = numbers
                    context_numbers = numbers[:3]
                    numbers_context = ", ".join(str(n) for n in numbers)
                    stats = _roulette_stats(numbers)
                    if stats:
                        stats_context = json.dumps(stats, ensure_ascii=False)
                    print(
                        "[agent] history context",
                        {
                            "roulette_id": roulette_id,
                            "use_history": use_history,
                            "history_limit": history_limit,
                            "head": numbers[:10],
                        },
                    )
            except Exception:
                numbers_context = ""

    history_lines = []
    history_window = 6 if is_realtime_update else 20
    for msg in state.get("messages", [])[-history_window:]:
        role = "Usuario" if msg.get("role") == "user" else "Agente"
        content = msg.get("content", "")
        history_lines.append(f"{role}: {content}")

    prompt_parts = [
        "Voce e um agente especializado em analisar padroes de roleta.",
        "Responda de forma objetiva e pratica.",
        "Regra fixa: quando mencionar vizinhos, use a ordem fisica da roleta europeia, nao a ordem numerica.",
        "Regra fixa: espelhos (pares fixos): 1-10, 2-20, 3-30, 6-9, 12-21, 13-31, 16-19, 23-32, 26-29.",
        "Ordem fisica da roleta europeia (sentido horario): 0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26.",
        "Exemplo vizinhos: os vizinhos imediatos de 20 sao 1 e 14.",
    ]
    compact_prompt = state.get("compact_prompt", "")
    if is_realtime_update:
        if not compact_prompt:
            compact_parts = []
            if template_prompt:
                compact_parts.append(template_prompt)
            if session_rules:
                active_rules = [r["text"] for r in session_rules if r.get("active")]
                if active_rules:
                    compact_parts.append("Regras do modelo ativas:\n- " + "\n- ".join(active_rules))
            if fixed_rules:
                compact_parts.append("Regras fixas:\n" + fixed_rules)
            if compact_parts:
                joined = "\n\n".join(compact_parts)
                compact_prompt = re.sub(r"\s+", " ", joined).strip()
                compact_prompt = compact_prompt[:1200] + ("..." if len(compact_prompt) > 1200 else "")
    if template_prompt and not is_realtime_update:
        prompt_parts.append(f"Modelo de chat:\n{template_prompt}")
    if compact_prompt and is_realtime_update:
        prompt_parts.append(f"Contexto compacto:\n{compact_prompt}")
    prompt_parts.append(f"Modo de saida preferido: {template_output_mode}")
    if session_rules:
        active_rules = [r["text"] for r in session_rules if r.get("active")]
        if active_rules and not is_realtime_update:
            prompt_parts.append("Regras do modelo ativas:\n- " + "\n- ".join(active_rules))
    if tool_result:
        prompt_parts.append(
            "Dados MCP (JSON):\n" + json.dumps(
                {"tool": tool_used, "result": tool_result},
                ensure_ascii=False,
            )
        )
    if roulette_id:
        prompt_parts.append(f"Roleta selecionada: {roulette_id}")
        roulette_info = roulette_lookup.get(roulette_id)
        if roulette_info:
            prompt_parts.append(
                f"Info roleta: nome={roulette_info.get('name')} url={roulette_info.get('url')}"
            )
    if fixed_rules and not is_realtime_update:
        prompt_parts.append(f"Regras fixas:\n{fixed_rules}")
    if numbers_context and use_history:
        prompt_parts.append(f"Ultimos numeros:\n{numbers_context}")
    if stats_context and use_history and not is_realtime_update:
        prompt_parts.append(f"Estatisticas e grupos:\n{stats_context}")
    if history_lines and not is_realtime_update:
        prompt_parts.append("Historico recente:\n" + "\n".join(history_lines))
    prompt_parts.append(f"Comando atual:\n{user_text}")

    direct_mode = False
    if tool_result:
        if tool_used == "context_recent_numbers":
            direct_mode = True
        if re.match(r"^(busque|buscar|mostre|traga|retorne|liste)", normalized_text):
            direct_mode = True
        if "analise" in normalized_text or "sugira" in normalized_text:
            direct_mode = False

    usage_meta: Dict[str, Any] = {}
    if direct_mode and tool_result:
        tool_table = ""
        if tool_used == "get_last_numbers":
            rows = tool_result.get("results", [])
            tool_table = "Resultados:\n" + (" · ".join(map(str, rows)) if rows else "-")
        elif tool_used == "get_following_numbers":
            rows = tool_result.get("results", [])
            header = "| Ocorrência | Próximos |\n|---:|:---|\n"
            body = "\n".join([
                f"| {item.get('occurrence_index')} | {', '.join(map(str, item.get('next_numbers', [])))} |"
                for item in rows
            ])
            tool_table = header + (body or "| - | - |")
        elif tool_used == "get_roulette_stats":
            stats = tool_result.get("stats", {})
            if stats:
                tool_table = (
                    "| Métrica | Valor |\n|:---|---:|\n"
                    f"| Total | {stats.get('total')} |\n"
                    f"| Pares (%) | {stats.get('parity', {}).get('par', {}).get('percent', 0)} |\n"
                    f"| Ímpares (%) | {stats.get('parity', {}).get('impar', {}).get('percent', 0)} |\n"
                    f"| Vermelhos (%) | {stats.get('colors', {}).get('vermelho', {}).get('percent', 0)} |\n"
                    f"| Pretos (%) | {stats.get('colors', {}).get('preto', {}).get('percent', 0)} |\n"
                )
        elif tool_used == "get_numbers_by_time_window":
            rows = tool_result.get("results", [])
            header = "| Horário (BR) | Número |\n|:---|---:|\n"
            body = "\n".join([
                f"| {item.get('timestamp_br','-')} | {item.get('value')} |" for item in rows[:50]
            ])
            tool_table = header + body

        assistant_reply = "```json\n" + json.dumps(
            {"tool": tool_used, "result": tool_result},
            ensure_ascii=False,
            indent=2,
        ) + "\n```\n\n" + (tool_table or "Tabela: sem dados")
    else:
        try:
            print(f"[agent] llm request provider={LLM_PROVIDER} model={model} roulette_id={roulette_id}")
            llm_result = await asyncio.to_thread(
                _call_llm_sync,
                model,
                "\n\n".join(prompt_parts),
            )
            assistant_reply = (llm_result.get("text") or "").strip() or "Sem resposta."
            usage = llm_result.get("usage") or {}
            total_tokens = (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0)
            cost = _estimate_cost(LLM_PROVIDER, model, usage)
            usage_meta = {
                "provider": LLM_PROVIDER,
                "model": model,
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "total_tokens": total_tokens,
                "cost_usd": cost,
            }
        except Exception as exc:
            print(f"[agent] llm error provider={LLM_PROVIDER}: {exc}")
            assistant_reply = (
                "Erro ao consultar o provedor de IA. Verifique a chave e o pagamento da sua conta."
            )

    updates: Dict[str, Any] = {
        "updated_at": datetime.utcnow(),
        "model": model,
        "use_history": use_history,
        "history_limit": history_limit,
        "recent_numbers": recent_numbers,
        "template_id": payload.template_id or state.get("template_id"),
        "template_prompt": template_prompt,
        "template_output_mode": template_output_mode,
        "compact_prompt": compact_prompt or state.get("compact_prompt", ""),
        "session_rules": session_rules,
    }
    if payload.roulette_id is not None:
        updates["roulette_id"] = payload.roulette_id
    if payload.fixed_rules is not None:
        updates["fixed_rules"] = payload.fixed_rules

    messages_to_add = []
    if payload.text.strip():
        messages_to_add.append({"role": "user", "content": payload.text.strip()})
    messages_to_add.append({
        "role": "assistant",
        "content": assistant_reply,
        "meta": {
            "context_numbers": context_numbers,
            "tool_used": tool_used,
            "tool_result": tool_result,
            "usage": usage_meta or None,
        },
    })

    await agent_sessions_coll.update_one(
        {"session_id": payload.session_id},
        {
            "$set": updates,
            "$setOnInsert": {"created_at": datetime.utcnow()},
            "$push": {
                "messages": {
                    "$each": messages_to_add,
                    "$slice": -MAX_MESSAGES,
                }
            },
        },
        upsert=True,
    )

    state = await _load_state(payload.session_id)
    state.pop("_id", None)
    return {"reply": assistant_reply, "state": _serialize_state(state)}


@router.post("/api/agent/prediction")
async def agent_prediction(payload: AgentPredictionIn) -> Dict[str, Any]:
    model = (payload.model or (DEFAULT_MODELS[0] if DEFAULT_MODELS else "gpt-4.1")).strip()
    history = payload.history or []
    stats = payload.stats or {}
    base = payload.suggestion_base or []
    extended = payload.suggestion_extended or []
    tooltip_number = payload.tooltip_number
    tooltip_data = payload.tooltip_data or {}

    # Validate and reduce tooltip payload
    if tooltip_data:
        allowed_keys = {
            "occurrences",
            "pulled",
            "pulledCounts",
            "topPulledItems",
            "bucket",
            "confidence",
            "suggestionList",
            "extendedList",
        }
        if not isinstance(tooltip_data, dict):
            tooltip_data = {}
        else:
            tooltip_data = {k: v for k, v in tooltip_data.items() if k in allowed_keys}

        # Truncate long arrays to keep payload small
        for key in ("occurrences", "pulled", "suggestionList", "extendedList"):
            if isinstance(tooltip_data.get(key), list):
                tooltip_data[key] = tooltip_data[key][:50]
        if isinstance(tooltip_data.get("topPulledItems"), list):
            tooltip_data["topPulledItems"] = tooltip_data["topPulledItems"][:18]
    else:
        raise HTTPException(status_code=400, detail="tooltip_data vazio. Reenvie com os dados do tooltip.")

    prompt = "\n\n".join([
        "Voce e um analista profissional de roleta ao vivo.",
        "Use apenas os dados fornecidos. Nao invente numeros.",
        "Regra fixa: a lista de historico esta do mais novo para o mais antigo (primeiro = ultimo que saiu).",
        "Regra fixa: vizinhos usam ordem fisica da roleta europeia.",
        "Objetivo: gerar uma sugestao pratica, cruzando numeros quentes e frios.",
        "Regra obrigatoria: existe um numero base (primeiro da lista do historico).",
        "Voce deve analisar o comportamento passado desse numero base usando tooltip_data (ocorrencias, puxou, buckets).",
        "Cruze esse comportamento com o contexto atual (stats e history) para decidir a sugestao.",
        "Se houver homogeneidade baixa entre as secoes, reduza a confianca.",
        "Responda apenas em JSON valido.",
        "",
        "Dados (JSON):",
        json.dumps(
            {
                "roulette_id": payload.roulette_id,
                "history": history,
                "stats": stats,
                "suggestion_base": base,
                "suggestion_extended": extended,
                "tooltip_number": tooltip_number,
                "tooltip_data": tooltip_data,
            },
            ensure_ascii=False,
        ),
        "",
        "Formato de resposta (JSON):",
        '{ "suggestion": [n1,n2,...], "extended": [n1,n2,...], "confidence": "baixa|media|alta", "explanation": "texto curto" }',
    ])

    usage_meta: Dict[str, Any] = {}
    try:
        logger.info(
            "[agent] prediction payload roulette_id=%s tooltip_number=%s history=%s stats_keys=%s tooltip_keys=%s",
            payload.roulette_id,
            tooltip_number,
            len(history),
            list((stats or {}).keys()),
            list((tooltip_data or {}).keys()),
        )
        if isinstance(tooltip_data, dict):
            occ = tooltip_data.get("occurrences") or []
            if isinstance(occ, list) and len(occ) < 3:
                logger.warning(
                    "[agent] prediction low occurrences for base=%s occurrences=%s",
                    tooltip_number,
                    len(occ),
                )
        llm_result = await asyncio.to_thread(_call_llm_sync, model, prompt)
        raw_text = (llm_result.get("text") or "").strip() or "{}"
        usage = llm_result.get("usage") or {}
        total_tokens = (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0)
        cost = _estimate_cost(LLM_PROVIDER, model, usage)
        usage_meta = {
            "provider": LLM_PROVIDER,
            "model": model,
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "total_tokens": total_tokens,
            "cost_usd": cost,
        }
        parsed: Dict[str, Any] = {}
        try:
            parsed = json.loads(raw_text)
        except Exception:
            parsed = {}
        # Fallback: extract suggestion from plain text if needed
        if not isinstance(parsed, dict) or not parsed:
            parsed = {
                "suggestion": [],
                "extended": [],
                "confidence": "baixa",
                "explanation": raw_text,
            }
        # Normalize required fields
        if "suggestion" not in parsed or not isinstance(parsed.get("suggestion"), list):
            parsed["suggestion"] = []
        if "extended" not in parsed or not isinstance(parsed.get("extended"), list):
            parsed["extended"] = []
        if "confidence" not in parsed:
            parsed["confidence"] = "baixa"
        if "explanation" not in parsed:
            parsed["explanation"] = raw_text

        # If suggestion is empty, try extract from raw_text
        if not parsed["suggestion"]:
            patterns = [
                r"Sugest[aã]o IA[:\s]*([0-9,\s]+)",
                r"Sugest[aã]o de aposta[:\s]*([0-9,\s]+)",
                r"Sugest[aã]o[:\s]*([0-9,\s]+)",
            ]
            extracted: List[int] = []
            for pat in patterns:
                m = re.search(pat, raw_text, re.IGNORECASE)
                if m:
                    extracted = [int(n) for n in re.findall(r"\d+", m.group(1))]
                    break
            if not extracted:
                # pick the longest list of comma-separated numbers
                candidates = re.findall(r"((?:\d{1,2}\s*,\s*)+\d{1,2})", raw_text)
                if candidates:
                    best = max(candidates, key=lambda s: s.count(","))
                    extracted = [int(n) for n in re.findall(r"\d+", best)]
            parsed["suggestion"] = extracted

        # Validate suggestions: 0-36, unique, sorted
        def _clean_nums(nums: List[Any]) -> List[int]:
            cleaned = []
            for n in nums:
                try:
                    v = int(n)
                except Exception:
                    continue
                if 0 <= v <= 36:
                    cleaned.append(v)
            return sorted(list(dict.fromkeys(cleaned)))

        parsed["suggestion"] = _clean_nums(parsed.get("suggestion", []))
        parsed["extended"] = _clean_nums(parsed.get("extended", []))

        return {"text": raw_text, "json": parsed, "usage": usage_meta}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/agent/roulettes")
async def list_agent_roulettes() -> Dict[str, Any]:
    return {
        "roulettes": [
            {
                "id": r["slug"],
                "name": r["name"],
                "url": r.get("url"),
            }
            for r in roulettes
        ]
    }


@router.get("/api/agent/models")
async def list_agent_models() -> Dict[str, Any]:
    return {"models": DEFAULT_MODELS}


@router.get("/api/agent/templates")
async def list_agent_templates(limit: int = Query(100, ge=1, le=500)) -> Dict[str, Any]:
    cursor = agent_templates_coll.find({}).sort("created_at", -1).limit(limit)
    templates = []
    async for doc in cursor:
        templates.append({
            "id": str(doc.get("_id")),
            "name": doc.get("name"),
            "prompt": doc.get("prompt"),
            "rules": doc.get("rules", []),
            "output_mode": doc.get("output_mode", "text"),
            "created_at": doc.get("created_at").isoformat() if doc.get("created_at") else None,
        })
    return {"templates": templates}


@router.post("/api/agent/templates")
async def create_agent_template(payload: AgentTemplateIn) -> Dict[str, Any]:
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Nome do modelo vazio.")
    if not payload.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt vazio.")
    rules = _normalize_rules(payload.rules)
    output_mode = _normalize_output_mode(payload.output_mode)
    doc = {
        "name": payload.name.strip(),
        "prompt": payload.prompt.strip(),
        "rules": rules,
        "output_mode": output_mode,
        "created_at": datetime.utcnow(),
    }
    result = await agent_templates_coll.insert_one(doc)
    return {"id": str(result.inserted_id)}


@router.put("/api/agent/templates")
async def update_agent_template(
    template_id: str = Query(...),
    payload: AgentTemplateIn = Body(...),
) -> Dict[str, str]:
    from bson import ObjectId

    try:
        _id = ObjectId(template_id)
    except Exception:
        raise HTTPException(status_code=400, detail="template_id invalido.")
    rules = _normalize_rules(payload.rules)
    output_mode = _normalize_output_mode(payload.output_mode)
    await agent_templates_coll.update_one(
        {"_id": _id},
        {"$set": {
            "name": payload.name.strip(),
            "prompt": payload.prompt.strip(),
            "rules": rules,
            "output_mode": output_mode,
        }},
    )
    return {"status": "ok"}


@router.delete("/api/agent/templates")
async def delete_agent_template(template_id: str = Query(...)) -> Dict[str, str]:
    from bson import ObjectId

    try:
        _id = ObjectId(template_id)
    except Exception:
        raise HTTPException(status_code=400, detail="template_id invalido.")
    await agent_templates_coll.delete_one({"_id": _id})
    return {"status": "deleted"}


@router.get("/api/agent/sessions")
async def list_agent_sessions(limit: int = Query(50, ge=1, le=200)) -> Dict[str, Any]:
    cursor = agent_sessions_coll.find({}).sort("updated_at", -1).limit(limit)
    sessions = []
    async for doc in cursor:
        sessions.append({
            "session_id": doc.get("session_id"),
            "roulette_id": doc.get("roulette_id"),
            "created_at": doc.get("created_at").isoformat() if doc.get("created_at") else None,
            "updated_at": doc.get("updated_at").isoformat() if doc.get("updated_at") else None,
            "message_count": len(doc.get("messages", [])),
            "model": doc.get("model"),
        })
    return {"sessions": sessions}


@router.delete("/api/agent/session")
async def delete_agent_session(session_id: str = Query(...)) -> Dict[str, str]:
    await agent_sessions_coll.delete_one({"session_id": session_id})
    return {"status": "deleted"}


@router.post("/api/agent/session/clone")
async def clone_agent_session(payload: AgentCloneIn) -> Dict[str, str]:
    source = await _load_state(payload.session_id)
    source.pop("_id", None)
    new_id = str(uuid4())
    source["session_id"] = new_id
    source["created_at"] = datetime.utcnow()
    source["updated_at"] = datetime.utcnow()
    await _save_state(source)
    return {"session_id": new_id}


@router.get("/api/agent/last-numbers")
async def get_agent_last_numbers(
    roulette_id: str = Query(...),
    limit: int = Query(50, ge=1, le=5000),
) -> Dict[str, Any]:
    try:
        numbers = await _fetch_recent_numbers(roulette_id, limit)
        return {
            "roulette_id": roulette_id,
            "results": numbers,
            "count": len(numbers),
            "order": "desc",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

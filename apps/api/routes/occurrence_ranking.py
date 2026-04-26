from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api.core.db import (
    ensure_occurrence_analysis_indexes,
    history_coll,
    occurrence_analysis_events_coll,
    occurrence_analysis_runs_coll,
)
from api.services.occurrence_live_control import (
    DEFAULT_API_BASE_URL,
    get_occurrence_live_status,
    list_occurrence_live_processes,
    start_occurrence_live_monitor,
    stop_occurrence_live_monitor,
)
from api.services.occurrence_ranking import (
    DEFAULT_ATTEMPTS_WINDOW,
    DEFAULT_HISTORY_LIMIT,
    DEFAULT_INVERT_CHECK_WINDOW,
    DEFAULT_RANKING_SIZE,
    DEFAULT_WINDOW_AFTER,
    DEFAULT_WINDOW_BEFORE,
    MAX_ATTEMPTS_WINDOW,
    MAX_HISTORY_LIMIT,
    MAX_INVERT_CHECK_WINDOW,
    build_occurrence_snapshot,
    normalize_history_desc,
    run_occurrence_replay,
)


router = APIRouter()


class OccurrenceRankingRequest(BaseModel):
    roulette_id: str | None = None
    slug: str | None = None
    history: List[int] = Field(default_factory=list)
    focus_number: int | None = None
    from_index: int = 0
    history_limit: int = DEFAULT_HISTORY_LIMIT
    window_before: int = DEFAULT_WINDOW_BEFORE
    window_after: int = DEFAULT_WINDOW_AFTER
    ranking_size: int = DEFAULT_RANKING_SIZE
    attempts_window: int = DEFAULT_ATTEMPTS_WINDOW
    invert_check_window: int = DEFAULT_INVERT_CHECK_WINDOW


class OccurrenceReplayRequest(BaseModel):
    roulette_id: str | None = None
    slug: str | None = None
    history: List[int] = Field(default_factory=list)
    history_limit: int = DEFAULT_HISTORY_LIMIT
    entries_limit: int = 300
    window_before: int = DEFAULT_WINDOW_BEFORE
    window_after: int = DEFAULT_WINDOW_AFTER
    ranking_size: int = DEFAULT_RANKING_SIZE
    attempts_window: int = DEFAULT_ATTEMPTS_WINDOW
    invert_check_window: int = DEFAULT_INVERT_CHECK_WINDOW
    focus_number_filter: int | None = None
    persist: bool = True
    include_event_preview: bool = True
    event_preview_limit: int = 25


class OccurrenceLiveControlRequest(BaseModel):
    roulette_id: str | None = None
    slug: str | None = None
    api_base_url: str | None = None
    history_limit: int = DEFAULT_HISTORY_LIMIT
    window_before: int = DEFAULT_WINDOW_BEFORE
    window_after: int = DEFAULT_WINDOW_AFTER
    ranking_size: int = DEFAULT_RANKING_SIZE
    attempts_window: int = DEFAULT_ATTEMPTS_WINDOW
    invert_check_window: int = DEFAULT_INVERT_CHECK_WINDOW


class OccurrenceLiveCleanupRequest(BaseModel):
    roulette_id: str | None = None


class OccurrenceRunCleanupRequest(BaseModel):
    roulette_id: str | None = None
    mode: str | None = None


def _resolve_roulette_id(*values: Any) -> str:
    for raw in values:
        text = str(raw or "").strip()
        if text:
            return text
    return ""


def _serialize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _serialize_value(item) for key, item in value.items()}
    return value


def _sanitize_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = {}
    for key, value in dict(doc or {}).items():
        if key == "_id":
            sanitized[key] = str(value)
            continue
        sanitized[key] = _serialize_value(value)
    return sanitized


def _is_run_deletable(run_doc: Dict[str, Any]) -> bool:
    status = str(run_doc.get("status") or "").strip().lower()
    return status not in {"running", "scheduled"}


async def _cleanup_occurrence_runs(
    *,
    roulette_id: str | None = None,
    mode: str | None = None,
) -> Dict[str, Any]:
    filters: Dict[str, Any] = {
        "status": {"$nin": ["running", "scheduled"]},
    }
    safe_roulette_id = _resolve_roulette_id(roulette_id)
    if safe_roulette_id:
        filters["roulette_id"] = safe_roulette_id
    safe_mode = str(mode or "").strip()
    if safe_mode:
        filters["mode"] = safe_mode

    cursor = occurrence_analysis_runs_coll.find(filters, {"run_id": 1})
    run_docs = await cursor.to_list(length=5000)
    run_ids = [
        str(doc.get("run_id") or "").strip()
        for doc in run_docs
        if str(doc.get("run_id") or "").strip()
    ]
    if not run_ids:
        return {
            "ok": True,
            "deleted_run_count": 0,
            "deleted_event_count": 0,
            "deleted_run_ids": [],
            "has_more_deleted_runs": False,
        }

    events_result = await occurrence_analysis_events_coll.delete_many({"run_id": {"$in": run_ids}})
    runs_result = await occurrence_analysis_runs_coll.delete_many({"run_id": {"$in": run_ids}})
    return {
        "ok": True,
        "deleted_run_count": int(runs_result.deleted_count),
        "deleted_event_count": int(events_result.deleted_count),
        "deleted_run_ids": run_ids[:100],
        "has_more_deleted_runs": len(run_ids) > 100,
    }


async def _fetch_history_docs_desc(roulette_id: str, history_limit: int) -> List[Dict[str, Any]]:
    safe_limit = max(1, min(MAX_HISTORY_LIMIT, int(history_limit)))
    cursor = (
        history_coll
        .find({"roulette_id": roulette_id})
        .sort("timestamp", -1)
        .limit(safe_limit)
    )
    return await cursor.to_list(length=safe_limit)


async def _fetch_latest_run_doc(roulette_id: str, *, mode: str | None = None) -> Dict[str, Any] | None:
    filters: Dict[str, Any] = {"roulette_id": roulette_id}
    if str(mode or "").strip():
        filters["mode"] = str(mode).strip()
    return await occurrence_analysis_runs_coll.find_one(filters, sort=[("created_at_utc", -1)])


async def _reconcile_live_runs_for_roulette(roulette_id: str) -> int:
    safe_roulette_id = str(roulette_id or "").strip()
    if not safe_roulette_id:
        return 0

    cursor = (
        occurrence_analysis_runs_coll
        .find(
            {
                "mode": "live",
                "roulette_id": safe_roulette_id,
                "status": {"$in": ["running", "scheduled"]},
            }
        )
        .sort("created_at_utc", -1)
    )
    live_runs = await cursor.to_list(length=100)
    if not live_runs:
        return 0

    active_processes = list_occurrence_live_processes(safe_roulette_id)
    keep_count = len(active_processes)
    stale_runs = live_runs[keep_count:] if keep_count >= 0 else live_runs
    stale_run_ids = [
        str(doc.get("run_id") or "").strip()
        for doc in stale_runs
        if str(doc.get("run_id") or "").strip()
    ]
    if not stale_run_ids:
        return 0

    updated_at_utc = datetime.now(timezone.utc)
    await occurrence_analysis_runs_coll.update_many(
        {"run_id": {"$in": stale_run_ids}},
        {
            "$set": {
                "status": "stopped",
                "updated_at_utc": updated_at_utc,
                "reconciled_reason": "process_missing_or_superseded",
            }
        },
    )
    return len(stale_run_ids)


async def _reconcile_live_run_statuses(roulette_id: str | None = None) -> int:
    safe_roulette_id = str(roulette_id or "").strip()
    if safe_roulette_id:
        return await _reconcile_live_runs_for_roulette(safe_roulette_id)

    roulette_ids = await occurrence_analysis_runs_coll.distinct(
        "roulette_id",
        {
            "mode": "live",
            "status": {"$in": ["running", "scheduled"]},
        },
    )
    reconciled = 0
    for roulette_value in roulette_ids:
        reconciled += await _reconcile_live_runs_for_roulette(str(roulette_value or "").strip())
    return reconciled


def _build_run_summary(
    *,
    roulette_id: str,
    mode: str,
    config: Dict[str, Any],
    result: Dict[str, Any],
    run_id: str,
    created_at_utc: datetime,
    status: str,
) -> Dict[str, Any]:
    return {
        "run_id": run_id,
        "roulette_id": roulette_id,
        "mode": mode,
        "status": status,
        "config": config,
        "history_size": int(result.get("history_size", 0) or 0),
        "entries_processed": int(result.get("entries_processed", 0) or 0),
        "entries_analyzed": int(result.get("entries_analyzed", 0) or 0),
        "eligible_entries": int(result.get("eligible_entries", 0) or 0),
        "cancelled_inverted_events": int(result.get("cancelled_inverted_events", 0) or 0),
        "events_with_hits": int(result.get("events_with_hits", 0) or 0),
        "total_hits": int(result.get("total_hits", 0) or 0),
        "total_attempts": int(result.get("total_attempts", 0) or 0),
        "aggregate_hit_rate": float(result.get("aggregate_hit_rate", 0.0) or 0.0),
        "event_hit_rate": float(result.get("event_hit_rate", 0.0) or 0.0),
        "avg_hits_per_event": float(result.get("avg_hits_per_event", 0.0) or 0.0),
        "first_hit_distribution": dict(result.get("first_hit_distribution") or {}),
        "created_at_utc": created_at_utc,
        "updated_at_utc": created_at_utc,
    }


def _attach_anchor_metadata(
    event: Dict[str, Any],
    history_docs_desc: List[Dict[str, Any]],
) -> Dict[str, Any]:
    enriched = dict(event)
    from_index = int(event.get("from_index", -1) or -1)
    if 0 <= from_index < len(history_docs_desc):
        anchor_doc = history_docs_desc[from_index]
        enriched["anchor_history_id"] = str(anchor_doc.get("_id")) if anchor_doc.get("_id") is not None else None
        enriched["anchor_timestamp_utc"] = _serialize_value(anchor_doc.get("timestamp"))
        enriched["anchor_number_db"] = anchor_doc.get("value")
        enriched["anchor_roulette_name"] = anchor_doc.get("roulette_name")
    else:
        enriched["anchor_history_id"] = None
        enriched["anchor_timestamp_utc"] = None
        enriched["anchor_number_db"] = None
        enriched["anchor_roulette_name"] = None
    return enriched


def _build_event_doc(
    *,
    run_id: str,
    roulette_id: str,
    mode: str,
    event: Dict[str, Any],
    created_at_utc: datetime,
) -> Dict[str, Any]:
    evaluation = dict(event.get("evaluation") or {})
    return {
        "event_id": str(uuid4()),
        "run_id": run_id,
        "roulette_id": roulette_id,
        "mode": mode,
        "status": str(event.get("status") or "resolved"),
        "created_at_utc": created_at_utc,
        "updated_at_utc": created_at_utc,
        "anchor_number": int(event.get("anchor_number", -1) or -1),
        "from_index": int(event.get("from_index", 0) or 0),
        "focus_number": int(event.get("focus_number", -1) or -1),
        "occurrence_count": int(event.get("occurrence_count", 0) or 0),
        "pulled_total": int(event.get("pulled_total", 0) or 0),
        "ranking": [int(number) for number in (event.get("ranking") or [])],
        "ranking_details": list(event.get("ranking_details") or []),
        "window_before": int(event.get("window_before", 0) or 0),
        "window_after": int(event.get("window_after", 0) or 0),
        "ranking_size": int(event.get("ranking_size", 0) or 0),
        "attempts_window": int(event.get("attempts_window", 0) or 0),
        "invert_check_window": int(event.get("invert_check_window", 0) or 0),
        "history_size": int(event.get("history_size", 0) or 0),
        "source": str(event.get("source") or "tooltip_occurrences_v1"),
        "explanation": str(event.get("explanation") or ""),
        "summary": str(event.get("summary") or ""),
        "counted": bool(event.get("counted", True)),
        "cancelled_reason": event.get("cancelled_reason"),
        "hit_count": int(event.get("hit_count", 0) or 0),
        "hit_attempts": list(event.get("hit_attempts") or []),
        "first_hit_attempt": event.get("first_hit_attempt"),
        "future_numbers": list(event.get("future_numbers") or []),
        "attempts": list(event.get("attempts") or []),
        "evaluation": evaluation,
        "inverted_evaluation": dict(event.get("inverted_evaluation") or {}),
        "anchor_history_id": event.get("anchor_history_id"),
        "anchor_timestamp_utc": event.get("anchor_timestamp_utc"),
        "anchor_number_db": event.get("anchor_number_db"),
        "anchor_roulette_name": event.get("anchor_roulette_name"),
    }


@router.post("/api/occurrences/ranking")
async def get_occurrence_ranking(payload: OccurrenceRankingRequest) -> Dict[str, Any]:
    try:
        roulette_id = _resolve_roulette_id(payload.roulette_id, payload.slug)
        history_docs_desc: List[Dict[str, Any]] = []
        history_desc = normalize_history_desc(payload.history, history_limit=payload.history_limit)

        if not history_desc:
            if not roulette_id:
                raise HTTPException(
                    status_code=400,
                    detail="Informe `history` ou `roulette_id`/`slug` para calcular o ranking de ocorrencias.",
                )
            history_docs_desc = await _fetch_history_docs_desc(roulette_id, payload.history_limit)
            history_desc = [
                int(doc["value"])
                for doc in history_docs_desc
                if isinstance(doc, dict) and 0 <= int(doc.get("value", -1)) <= 36
            ]

        snapshot = build_occurrence_snapshot(
            history_desc,
            focus_number=payload.focus_number,
            from_index=payload.from_index,
            history_limit=payload.history_limit,
            window_before=payload.window_before,
            window_after=payload.window_after,
            ranking_size=payload.ranking_size,
            attempts_window=payload.attempts_window,
            invert_check_window=max(0, min(MAX_INVERT_CHECK_WINDOW, int(payload.invert_check_window))),
        )
        if roulette_id:
            snapshot["roulette_id"] = roulette_id
        if history_docs_desc and 0 <= int(snapshot.get("from_index", -1) or -1) < len(history_docs_desc):
            enriched = _attach_anchor_metadata(snapshot, history_docs_desc)
            snapshot.update(
                {
                    "anchor_history_id": enriched.get("anchor_history_id"),
                    "anchor_timestamp_utc": enriched.get("anchor_timestamp_utc"),
                    "anchor_number_db": enriched.get("anchor_number_db"),
                    "anchor_roulette_name": enriched.get("anchor_roulette_name"),
                }
            )
        return snapshot
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/occurrences/replay")
async def replay_occurrence_ranking(payload: OccurrenceReplayRequest) -> Dict[str, Any]:
    try:
        roulette_id = _resolve_roulette_id(payload.roulette_id, payload.slug)
        history_docs_desc: List[Dict[str, Any]] = []
        history_desc = normalize_history_desc(payload.history, history_limit=payload.history_limit)

        if not history_desc:
            if not roulette_id:
                raise HTTPException(
                    status_code=400,
                    detail="Informe `history` ou `roulette_id`/`slug` para rodar o replay de ocorrencias.",
                )
            history_docs_desc = await _fetch_history_docs_desc(roulette_id, payload.history_limit)
            history_desc = [
                int(doc["value"])
                for doc in history_docs_desc
                if isinstance(doc, dict) and 0 <= int(doc.get("value", -1)) <= 36
            ]

        if not roulette_id:
            roulette_id = "custom-history"

        result = run_occurrence_replay(
            roulette_id=roulette_id,
            history_desc=history_desc,
            history_limit=payload.history_limit,
            entries_limit=payload.entries_limit,
            window_before=payload.window_before,
            window_after=payload.window_after,
            ranking_size=payload.ranking_size,
            attempts_window=payload.attempts_window,
            invert_check_window=max(0, min(MAX_INVERT_CHECK_WINDOW, int(payload.invert_check_window))),
            focus_number_filter=payload.focus_number_filter,
        )
        if not result.get("available", False):
            return result

        enriched_events = [
            _attach_anchor_metadata(event, history_docs_desc)
            for event in result.get("events", [])
        ]
        result["events"] = enriched_events

        run_id = None
        stored_event_count = 0
        if payload.persist:
            await ensure_occurrence_analysis_indexes()
            created_at_utc = datetime.now(timezone.utc)
            run_id = str(uuid4())
            run_summary = _build_run_summary(
                roulette_id=roulette_id,
                mode="replay",
                config=dict(result.get("config") or {}),
                result=result,
                run_id=run_id,
                created_at_utc=created_at_utc,
                status="completed",
            )
            await occurrence_analysis_runs_coll.insert_one(run_summary)
            event_docs = [
                _build_event_doc(
                    run_id=run_id,
                    roulette_id=roulette_id,
                    mode="replay",
                    event=event,
                    created_at_utc=created_at_utc,
                )
                for event in enriched_events
            ]
            if event_docs:
                await occurrence_analysis_events_coll.insert_many(event_docs, ordered=False)
            stored_event_count = len(event_docs)

        safe_preview_limit = max(0, min(200, int(payload.event_preview_limit)))
        include_preview = bool(payload.include_event_preview)
        events_preview = enriched_events[:safe_preview_limit] if include_preview and safe_preview_limit > 0 else []
        response = {
            key: value
            for key, value in result.items()
            if key != "events"
        }
        response["run_id"] = run_id
        response["stored_event_count"] = stored_event_count
        response["events_preview"] = events_preview
        response["preview_event_count"] = len(events_preview)
        response["has_more_events"] = len(enriched_events) > len(events_preview)
        return response
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/occurrences/live/start")
async def start_occurrence_live(payload: OccurrenceLiveControlRequest) -> Dict[str, Any]:
    roulette_id = _resolve_roulette_id(payload.roulette_id, payload.slug)
    if not roulette_id:
        raise HTTPException(status_code=400, detail="roulette_id e obrigatorio.")

    try:
        status = start_occurrence_live_monitor(
            roulette_id=roulette_id,
            api_base_url=str(payload.api_base_url or "").strip() or DEFAULT_API_BASE_URL,
            history_limit=payload.history_limit,
            window_before=payload.window_before,
            window_after=payload.window_after,
            ranking_size=payload.ranking_size,
            attempts_window=payload.attempts_window,
            invert_check_window=max(0, min(MAX_INVERT_CHECK_WINDOW, int(payload.invert_check_window))),
        )
        return {
            "ok": True,
            "message": "Monitor ao vivo de ocorrencias iniciado.",
            "status": status,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/occurrences/live/stop")
async def stop_occurrence_live(payload: OccurrenceLiveControlRequest) -> Dict[str, Any]:
    roulette_id = _resolve_roulette_id(payload.roulette_id, payload.slug)
    if not roulette_id:
        raise HTTPException(status_code=400, detail="roulette_id e obrigatorio.")

    try:
        status = stop_occurrence_live_monitor(roulette_id)
        return {
            "ok": True,
            "message": "Monitor ao vivo de ocorrencias interrompido.",
            "status": status,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/occurrences/live/status/{roulette_id}")
async def get_occurrence_live_runtime_status(
    roulette_id: str,
    events_limit: int = Query(30, ge=0, le=200),
) -> Dict[str, Any]:
    safe_roulette_id = str(roulette_id or "").strip()
    if not safe_roulette_id:
        raise HTTPException(status_code=400, detail="roulette_id e obrigatorio.")

    try:
        await _reconcile_live_run_statuses(safe_roulette_id)
        process_status = get_occurrence_live_status(safe_roulette_id)
        latest_live_run = await _fetch_latest_run_doc(safe_roulette_id, mode="live")
        recent_events: List[Dict[str, Any]] = []
        total_recent_events = 0

        if latest_live_run:
            run_id = str(latest_live_run.get("run_id") or "").strip()
            if run_id:
                total_recent_events = await occurrence_analysis_events_coll.count_documents({"run_id": run_id})
                if int(events_limit) > 0:
                    cursor = (
                        occurrence_analysis_events_coll
                        .find({"run_id": run_id})
                        .sort("created_at_utc", -1)
                        .limit(int(events_limit))
                    )
                    docs = await cursor.to_list(length=int(events_limit))
                    recent_events = [_sanitize_doc(doc) for doc in docs]

        return {
            "ok": True,
            "roulette_id": safe_roulette_id,
            "process_status": process_status,
            "latest_live_run": _sanitize_doc(latest_live_run) if latest_live_run else None,
            "recent_events": recent_events,
            "recent_events_count": len(recent_events),
            "total_recent_events": int(total_recent_events),
            "has_more_recent_events": int(total_recent_events) > len(recent_events),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/occurrences/runs")
async def list_occurrence_runs(
    roulette_id: str | None = None,
    mode: str | None = None,
    status: str | None = None,
    limit: int = Query(20, ge=1, le=200),
) -> Dict[str, Any]:
    try:
        safe_mode = str(mode or "").strip()
        safe_roulette_id = str(roulette_id or "").strip()
        if not safe_mode or safe_mode == "live":
            await _reconcile_live_run_statuses(safe_roulette_id or None)

        filters: Dict[str, Any] = {}
        if safe_roulette_id:
            filters["roulette_id"] = safe_roulette_id
        if safe_mode:
            filters["mode"] = safe_mode
        if str(status or "").strip():
            filters["status"] = str(status).strip()

        cursor = (
            occurrence_analysis_runs_coll
            .find(filters)
            .sort("created_at_utc", -1)
            .limit(int(limit))
        )
        items = await cursor.to_list(length=int(limit))
        return {
            "items": [_sanitize_doc(item) for item in items],
            "count": len(items),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/occurrences/runs/{run_id}")
async def get_occurrence_run(
    run_id: str,
    events_limit: int = Query(100, ge=1, le=500),
    status: str | None = None,
) -> Dict[str, Any]:
    try:
        run_doc = await occurrence_analysis_runs_coll.find_one({"run_id": str(run_id)})
        if not run_doc:
            raise HTTPException(status_code=404, detail="Run de ocorrencias nao encontrado.")
        if str(run_doc.get("mode") or "").strip() == "live":
            await _reconcile_live_run_statuses(str(run_doc.get("roulette_id") or "").strip())
            run_doc = await occurrence_analysis_runs_coll.find_one({"run_id": str(run_id)})
            if not run_doc:
                raise HTTPException(status_code=404, detail="Run de ocorrencias nao encontrado.")

        event_filters: Dict[str, Any] = {"run_id": str(run_id)}
        if str(status or "").strip():
            event_filters["status"] = str(status).strip()

        cursor = (
            occurrence_analysis_events_coll
            .find(event_filters)
            .sort([("from_index", 1), ("created_at_utc", -1)])
            .limit(int(events_limit))
        )
        events = await cursor.to_list(length=int(events_limit))
        total_events = await occurrence_analysis_events_coll.count_documents(event_filters)
        return {
            "run": _sanitize_doc(run_doc),
            "events": [_sanitize_doc(item) for item in events],
            "events_count": len(events),
            "total_events": int(total_events),
            "has_more_events": int(total_events) > len(events),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/api/occurrences/runs/{run_id}")
async def delete_occurrence_run(run_id: str) -> Dict[str, Any]:
    safe_run_id = str(run_id or "").strip()
    if not safe_run_id:
        raise HTTPException(status_code=400, detail="run_id e obrigatorio.")

    try:
        run_doc = await occurrence_analysis_runs_coll.find_one({"run_id": safe_run_id})
        if not run_doc:
            raise HTTPException(status_code=404, detail="Run de ocorrencias nao encontrado.")
        if str(run_doc.get("mode") or "").strip() == "live":
            await _reconcile_live_run_statuses(str(run_doc.get("roulette_id") or "").strip())
            run_doc = await occurrence_analysis_runs_coll.find_one({"run_id": safe_run_id})
            if not run_doc:
                raise HTTPException(status_code=404, detail="Run de ocorrencias nao encontrado.")
        if not _is_run_deletable(run_doc):
            raise HTTPException(
                status_code=409,
                detail="Nao e possivel excluir uma live em andamento. Pare a live antes de excluir.",
            )

        events_result = await occurrence_analysis_events_coll.delete_many({"run_id": safe_run_id})
        run_result = await occurrence_analysis_runs_coll.delete_one({"run_id": safe_run_id})
        return {
            "ok": True,
            "run_id": safe_run_id,
            "deleted_run_count": int(run_result.deleted_count),
            "deleted_event_count": int(events_result.deleted_count),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/occurrences/live/runs/cleanup")
async def cleanup_finished_live_runs(payload: OccurrenceLiveCleanupRequest) -> Dict[str, Any]:
    try:
        return await _cleanup_occurrence_runs(
            roulette_id=payload.roulette_id,
            mode="live",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/occurrences/runs/cleanup")
async def cleanup_finished_occurrence_runs(payload: OccurrenceRunCleanupRequest) -> Dict[str, Any]:
    try:
        return await _cleanup_occurrence_runs(
            roulette_id=payload.roulette_id,
            mode=payload.mode,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

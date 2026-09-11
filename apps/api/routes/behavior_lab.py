from __future__ import annotations

import fcntl
import inspect
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal, Mapping

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool


ROULETTE_ID = "pragmatic-auto-roulette"
MAX_ATTEMPTS = 10
MAX_BACKTEST_RESULTS = 2_000
BACKTEST_MIN_INTERVAL_SECONDS = 30
BACKTEST_LOCK_PATH = Path("/tmp/revesbot-behavior-lab-backtest.lock")

router = APIRouter()
api_dir = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=api_dir / "templates")


def _asset_version() -> str:
    assets = (
        api_dir / "static/css/pages/behavior-lab.css",
        api_dir / "static/js/pages/behavior-lab.js",
    )
    timestamps = [int(path.stat().st_mtime) for path in assets if path.exists()]
    return str(max(timestamps, default=1))


def get_behavior_lab_facade() -> Any:
    """Load the independent behavior engine only when an API route needs it."""
    try:
        from behavior_lab import facade
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="Motor de comportamento indisponível",
        ) from exc
    return facade


def get_history_collection() -> Any:
    """Return the read-only result source; separated to keep route tests isolated."""
    from api.core.runtime_db import history_coll

    return history_coll


async def _await_result(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _require_mapping(value: Any, *, operation: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise HTTPException(
            status_code=503,
            detail=f"Resposta inválida ao {operation}",
        )
    return dict(value)


def _load_default_config(facade: Any) -> Any:
    try:
        return facade.load_config()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Configuração do motor indisponível",
        ) from exc


@contextmanager
def _exclusive_backtest():
    lock_handle = BACKTEST_LOCK_PATH.open("a+", encoding="utf-8")
    locked = False
    completed = False
    try:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except BlockingIOError as exc:
            raise HTTPException(
                status_code=429,
                detail="Já existe um backtest em execução",
            ) from exc
        lock_handle.seek(0)
        previous_text = lock_handle.read().strip()
        try:
            previous_completion = float(previous_text) if previous_text else 0.0
        except ValueError:
            previous_completion = 0.0
        retry_after = BACKTEST_MIN_INTERVAL_SECONDS - (time.time() - previous_completion)
        if retry_after > 0:
            raise HTTPException(
                status_code=429,
                detail=f"Aguarde {max(1, int(retry_after + 0.999))}s para outro backtest",
            )
        yield
        completed = True
    finally:
        try:
            if locked and completed:
                lock_handle.seek(0)
                lock_handle.truncate()
                lock_handle.write(str(time.time()))
                lock_handle.flush()
            if locked:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        finally:
            lock_handle.close()


class BehaviorBacktestRequest(BaseModel):
    limit: int = Field(default=2_000, ge=1, le=MAX_BACKTEST_RESULTS)


@router.get("/patterns/behavior-lab", response_class=HTMLResponse)
async def behavior_lab_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="behavior_lab.html",
        context={
            "asset_version": _asset_version(),
            "roulette_id": ROULETTE_ID,
            "max_attempts": MAX_ATTEMPTS,
            "max_backtest_results": MAX_BACKTEST_RESULTS,
        },
    )


@router.get("/api/patterns/behavior-lab/live")
async def behavior_lab_live(
    facade: Any = Depends(get_behavior_lab_facade),
) -> dict[str, Any]:
    try:
        payload = await _await_result(
            facade.read_live_state(config=_load_default_config(facade))
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Estado ao vivo indisponível",
        ) from exc
    return _require_mapping(payload, operation="consultar o estado ao vivo")


@router.get("/api/patterns/behavior-lab/signals")
async def behavior_lab_signals(
    limit: int = Query(default=50, ge=1, le=200),
    status: Literal["active", "won", "lost", "censored"] | None = None,
    facade: Any = Depends(get_behavior_lab_facade),
) -> dict[str, Any]:
    try:
        payload = await _await_result(
            facade.read_signals(
                limit=limit,
                status=status,
                config=_load_default_config(facade),
            )
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Sinais indisponíveis",
        ) from exc
    return _require_mapping(payload, operation="consultar os sinais")


@router.get("/api/patterns/behavior-lab/health")
async def behavior_lab_health(
    facade: Any = Depends(get_behavior_lab_facade),
) -> dict[str, Any]:
    try:
        payload = await _await_result(
            facade.read_health(config=_load_default_config(facade))
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Worker de comportamento indisponível",
        ) from exc
    return _require_mapping(payload, operation="consultar a saúde do worker")


@router.post("/api/patterns/behavior-lab/backtest")
async def behavior_lab_backtest(
    payload: BehaviorBacktestRequest,
    facade: Any = Depends(get_behavior_lab_facade),
    history_collection: Any = Depends(get_history_collection),
) -> dict[str, Any]:
    projection = {
        "value": 1,
        "timestamp": 1,
        "external_game_id": 1,
    }
    with _exclusive_backtest():
        try:
            cursor = history_collection.find(
                {"roulette_id": ROULETTE_ID},
                projection,
            ).sort([("timestamp", -1), ("_id", -1)]).limit(payload.limit)
            documents = await cursor.to_list(length=payload.limit)
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Histórico de resultados indisponível",
            ) from exc

        events = []
        for document in reversed(documents):
            if document.get("value") is None:
                continue
            timestamp = document.get("timestamp")
            events.append(
                {
                    "roulette_id": ROULETTE_ID,
                    "value": int(document["value"]),
                    "_id": str(document["_id"]) if document.get("_id") is not None else None,
                    "external_game_id": document.get("external_game_id"),
                    "timestamp": (
                        timestamp.isoformat()
                        if hasattr(timestamp, "isoformat")
                        else timestamp
                    ),
                }
            )
        if not events:
            raise HTTPException(
                status_code=422,
                detail="Não há resultados disponíveis para o backtest",
            )

        config = _load_default_config(facade)
        try:
            result = await run_in_threadpool(
                lambda: facade.run_backtest(
                    events,
                    config=config,
                    input_order="chronological",
                    include_decisions=False,
                    include_signals=False,
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail="Não foi possível executar o backtest",
            ) from exc

    response = _require_mapping(result, operation="executar o backtest")
    response.setdefault("roulette_id", ROULETTE_ID)
    response["results_loaded"] = len(events)
    response["results_used"] = int(
        response.get("metrics", {}).get("spins", {}).get("accepted", len(events))
    )
    response.setdefault("max_attempts", MAX_ATTEMPTS)
    return response

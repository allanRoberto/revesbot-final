from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "apps" / "monitoring" / "scripts" / "occurrence_live_monitor.py"
LOG_DIR = REPO_ROOT / "apps" / "api" / "data" / "occurrence_live_logs"
DEFAULT_API_BASE_URL = (os.getenv("BASE_URL_API") or "http://localhost:8080").rstrip("/")

_ACTIVE_PROCESSES: dict[str, subprocess.Popen] = {}
_PROCESS_STATUS: dict[str, Dict[str, Any]] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_int(raw: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _python_executable() -> str:
    override = str(os.getenv("OCCURRENCE_LIVE_MONITOR_PYTHON") or "").strip()
    if override:
        return override
    return sys.executable


def list_occurrence_live_processes(roulette_id: str | None = None) -> list[Dict[str, Any]]:
    safe_roulette_id = str(roulette_id or "").strip()
    script_marker = str(SCRIPT_PATH)
    try:
        result = subprocess.run(
            ["ps", "-ax", "-o", "pid=", "-o", "command="],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return []

    processes: list[Dict[str, Any]] = []
    for raw_line in str(result.stdout or "").splitlines():
        line = raw_line.strip()
        if not line or script_marker not in line:
            continue
        try:
            pid_part, command = line.split(None, 1)
            pid = int(pid_part)
        except (ValueError, TypeError):
            continue
        if safe_roulette_id and f"--slug {safe_roulette_id}" not in command:
            continue
        processes.append(
            {
                "pid": pid,
                "command": command,
            }
        )
    return processes


def _ensure_log_dir() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def _build_log_path(roulette_id: str) -> Path:
    safe_slug = "".join(ch for ch in roulette_id if ch.isalnum() or ch in {"-", "_"}).strip() or "roulette"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return LOG_DIR / f"{safe_slug}_{timestamp}.log"


def _build_status(
    *,
    roulette_id: str,
    state: str,
    history_limit: int,
    window_before: int,
    window_after: int,
    ranking_size: int,
    attempts_window: int,
    invert_check_window: int,
    api_base_url: str,
    pid: int | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    log_path: str = "",
    exit_code: int | None = None,
    error: str = "",
) -> Dict[str, Any]:
    return {
        "roulette_id": roulette_id,
        "state": state,
        "pid": pid,
        "started_at": started_at,
        "finished_at": finished_at,
        "history_limit": history_limit,
        "window_before": window_before,
        "window_after": window_after,
        "ranking_size": ranking_size,
        "attempts_window": attempts_window,
        "invert_check_window": invert_check_window,
        "api_base_url": api_base_url,
        "log_path": log_path,
        "exit_code": exit_code,
        "error": error,
    }


def _refresh_process_state(roulette_id: str) -> Dict[str, Any]:
    current = dict(_PROCESS_STATUS.get(roulette_id) or {})
    process = _ACTIVE_PROCESSES.get(roulette_id)
    if process is None:
        return current
    exit_code = process.poll()
    if exit_code is None:
        current["state"] = "running"
        current["pid"] = process.pid
        _PROCESS_STATUS[roulette_id] = current
        return current
    current["state"] = "exited" if exit_code == 0 else "failed"
    current["exit_code"] = int(exit_code)
    current["finished_at"] = current.get("finished_at") or _now_iso()
    current["pid"] = process.pid
    _PROCESS_STATUS[roulette_id] = current
    _ACTIVE_PROCESSES.pop(roulette_id, None)
    return current


def get_occurrence_live_status(roulette_id: str) -> Dict[str, Any]:
    safe_roulette_id = str(roulette_id or "").strip()
    if not safe_roulette_id:
        return {}
    current = _refresh_process_state(safe_roulette_id)
    if current:
        return dict(current)
    return _build_status(
        roulette_id=safe_roulette_id,
        state="idle",
        history_limit=2000,
        window_before=5,
        window_after=3,
        ranking_size=18,
        attempts_window=10,
        invert_check_window=0,
        api_base_url=DEFAULT_API_BASE_URL,
    )


def start_occurrence_live_monitor(
    *,
    roulette_id: str,
    api_base_url: str,
    history_limit: int,
    window_before: int,
    window_after: int,
    ranking_size: int,
    attempts_window: int,
    invert_check_window: int,
) -> Dict[str, Any]:
    safe_roulette_id = str(roulette_id or "").strip()
    if not safe_roulette_id:
        raise ValueError("roulette_id e obrigatorio.")
    if not SCRIPT_PATH.exists():
        raise FileNotFoundError(f"Script do monitor nao encontrado em {SCRIPT_PATH}")

    stop_occurrence_live_monitor(safe_roulette_id, wait_timeout=2.0, suppress_missing=True)

    safe_history_limit = _safe_int(history_limit, 2000, 1, 50_000)
    safe_window_before = _safe_int(window_before, 5, 0, 100)
    safe_window_after = _safe_int(window_after, 3, 0, 100)
    safe_ranking_size = _safe_int(ranking_size, 18, 1, 37)
    safe_attempts_window = _safe_int(attempts_window, 10, 1, 100)
    safe_invert_check_window = _safe_int(invert_check_window, 0, 0, 100)
    safe_api_base_url = str(api_base_url or DEFAULT_API_BASE_URL).rstrip("/")

    _ensure_log_dir()
    log_path = _build_log_path(safe_roulette_id)
    log_file = open(log_path, "ab")
    cmd = [
        _python_executable(),
        str(SCRIPT_PATH),
        "--slug",
        safe_roulette_id,
        "--api-base-url",
        safe_api_base_url,
        "--history-limit",
        str(safe_history_limit),
        "--window-before",
        str(safe_window_before),
        "--window-after",
        str(safe_window_after),
        "--ranking-size",
        str(safe_ranking_size),
        "--attempts-window",
        str(safe_attempts_window),
        "--invert-check-window",
        str(safe_invert_check_window),
    ]
    mongo_url = str(os.getenv("MONGO_URL") or os.getenv("mongo_url") or "").strip()
    mongo_db = str(os.getenv("MONGO_DB") or "roleta_db").strip() or "roleta_db"
    if mongo_url:
        cmd.extend(["--mongo-url", mongo_url, "--mongo-db", mongo_db])

    env = os.environ.copy()
    try:
        process = subprocess.Popen(
            cmd,
            cwd=str(REPO_ROOT),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
            env=env,
        )
    finally:
        log_file.close()
    _ACTIVE_PROCESSES[safe_roulette_id] = process
    status = _build_status(
        roulette_id=safe_roulette_id,
        state="running",
        pid=process.pid,
        history_limit=safe_history_limit,
        window_before=safe_window_before,
        window_after=safe_window_after,
        ranking_size=safe_ranking_size,
        attempts_window=safe_attempts_window,
        invert_check_window=safe_invert_check_window,
        api_base_url=safe_api_base_url,
        started_at=_now_iso(),
        log_path=str(log_path),
    )
    _PROCESS_STATUS[safe_roulette_id] = status
    return dict(status)


def stop_occurrence_live_monitor(
    roulette_id: str,
    *,
    wait_timeout: float = 5.0,
    suppress_missing: bool = False,
) -> Dict[str, Any]:
    safe_roulette_id = str(roulette_id or "").strip()
    if not safe_roulette_id:
        if suppress_missing:
            return {}
        raise ValueError("roulette_id e obrigatorio.")

    process = _ACTIVE_PROCESSES.get(safe_roulette_id)
    current = dict(_PROCESS_STATUS.get(safe_roulette_id) or {})
    if process is None:
        if suppress_missing:
            return get_occurrence_live_status(safe_roulette_id)
        if current:
            return current
        return _build_status(
            roulette_id=safe_roulette_id,
            state="idle",
            history_limit=2000,
            window_before=5,
            window_after=3,
            ranking_size=18,
            attempts_window=10,
            invert_check_window=0,
            api_base_url=DEFAULT_API_BASE_URL,
        )

    if process.poll() is None:
        try:
            process.terminate()
            process.wait(timeout=max(0.5, float(wait_timeout)))
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2.0)
        except ProcessLookupError:
            pass

    finished_at = _now_iso()
    current["state"] = "stopped"
    current["finished_at"] = finished_at
    current["exit_code"] = process.poll()
    current["pid"] = process.pid
    _PROCESS_STATUS[safe_roulette_id] = current
    _ACTIVE_PROCESSES.pop(safe_roulette_id, None)
    return dict(current)

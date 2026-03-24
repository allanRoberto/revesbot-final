from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Callable, Dict
from uuid import uuid4


class PatternTrainingJobsService:
    """Gerencia treinos longos em background com progresso em memoria."""

    def __init__(self) -> None:
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = Lock()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def create_job(self, *, params: Dict[str, Any]) -> Dict[str, Any]:
        job_id = str(uuid4())
        payload = {
            "job_id": job_id,
            "status": "queued",
            "created_at": self._now(),
            "updated_at": self._now(),
            "params": dict(params or {}),
            "progress": {
                "stage": "queued",
                "processed": 0,
                "total": 0,
                "progress": 0.0,
                "available_cases": 0,
                "hit_cases": 0,
            },
            "result": None,
            "error": None,
        }
        with self._lock:
            self._jobs[job_id] = payload
        return dict(payload)

    def get_job(self, job_id: str) -> Dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def update_progress(self, job_id: str, progress: Dict[str, Any]) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job["status"] = "running"
            job["updated_at"] = self._now()
            current = dict(job.get("progress", {}))
            current.update(dict(progress or {}))
            job["progress"] = current

    def complete_job(self, job_id: str, result: Dict[str, Any]) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job["status"] = "completed"
            job["updated_at"] = self._now()
            job["result"] = dict(result or {})
            progress = dict(job.get("progress", {}))
            progress.update(
                {
                    "stage": "completed",
                    "processed": int(progress.get("total", progress.get("processed", 0)) or 0),
                    "progress": 1.0,
                }
            )
            job["progress"] = progress

    def fail_job(self, job_id: str, error: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job["status"] = "failed"
            job["updated_at"] = self._now()
            job["error"] = str(error or "erro desconhecido")
            progress = dict(job.get("progress", {}))
            progress["stage"] = "failed"
            job["progress"] = progress

    async def run_in_background(
        self,
        *,
        job_id: str,
        worker: Callable[[], Dict[str, Any]],
    ) -> None:
        try:
            result = await asyncio.to_thread(worker)
            self.complete_job(job_id, result)
        except Exception as exc:  # pragma: no cover
            self.fail_job(job_id, str(exc))


pattern_training_jobs = PatternTrainingJobsService()

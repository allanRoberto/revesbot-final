from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from api.services.pattern_engine import PatternEngine

logger = logging.getLogger(__name__)


class PatternTelemetryService:
    """Stores signal events and computes pattern performance analytics."""

    def __init__(self, storage_path: Path | None = None) -> None:
        base_dir = Path(__file__).resolve().parent.parent
        data_dir = base_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        self._storage_path = storage_path or (data_dir / "pattern_events.jsonl")

    def append_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Appends event and updates correlation/decay modules if hit/miss is known."""
        now = datetime.now(timezone.utc).isoformat()
        payload = dict(event)
        payload.setdefault("event_id", str(uuid4()))
        payload.setdefault("created_at", now)
        with self._storage_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=True) + "\n")

        # Update correlation and decay modules based on progress
        self._update_assertiveness_modules(payload)

        return payload

    def _update_assertiveness_modules(self, event: Dict[str, Any]) -> None:
        """Updates correlation matrix and decay manager based on event result."""
        try:
            progress = event.get("progress", {})
            if not isinstance(progress, dict):
                return

            status = progress.get("status", "")
            if status not in ("hit", "miss"):
                return

            hit = status == "hit"

            # Get active patterns from event
            active_patterns = event.get("active_patterns", [])
            if not isinstance(active_patterns, list):
                return

            pattern_ids = [
                str(p.get("pattern_id", ""))
                for p in active_patterns
                if isinstance(p, dict) and p.get("pattern_id")
            ]

            if not pattern_ids:
                return

            # Get suggestion from event (if available)
            suggestion = event.get("suggestion", [])
            if not isinstance(suggestion, list):
                suggestion = []

            # Get actual number from progress
            actual_number = progress.get("hit_number")

            # Import and update modules
            from api.services.pattern_engine import pattern_engine
            pattern_engine.record_signal_result(
                active_patterns=pattern_ids,
                hit=hit,
                suggested_numbers=suggestion,
                actual_number=actual_number,
            )

        except Exception as exc:
            logger.warning("Error updating assertiveness modules: %s", exc)

    def read_events(self, limit: int = 5000) -> List[Dict[str, Any]]:
        if not self._storage_path.exists():
            return []
        lines = self._storage_path.read_text(encoding="utf-8").splitlines()
        if limit > 0:
            lines = lines[-limit:]
        events: List[Dict[str, Any]] = []
        for line in lines:
            try:
                events.append(json.loads(line))
            except Exception:
                continue
        return events

    @staticmethod
    def evaluate_progress(
        suggestion_list: List[int],
        history: List[int],
        from_index: int,
        max_attempts: int = 12,
    ) -> Dict[str, Any]:
        idx = max(0, int(from_index))
        if not suggestion_list:
            return {"status": "unavailable", "attempts": 0, "hit_number": None}
        if idx <= 0:
            return {"status": "pending", "attempts": 0, "hit_number": None}
        suggestion_set = set(int(n) for n in suggestion_list if isinstance(n, int) or str(n).isdigit())
        max_steps = min(idx, max(1, int(max_attempts)))
        for step in range(1, max_steps + 1):
            look_idx = idx - step
            if look_idx < 0:
                break
            value = int(history[look_idx])
            if value in suggestion_set:
                return {"status": "hit", "attempts": step, "hit_number": value}
        return {"status": "pending", "attempts": 0, "hit_number": None}

    def summarize_events(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        by_pattern: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {
                "pattern_id": "",
                "hits": 0,
                "misses": 0,
                "pending": 0,
                "signals": 0,
                "avg_attempt_hit": 0.0,
                "attempt_sum": 0.0,
                "attempt_count": 0,
            }
        )
        totals = {"events": 0, "hits": 0, "misses": 0, "pending": 0, "unavailable": 0}
        for ev in events:
            totals["events"] += 1
            progress = ev.get("progress", {}) if isinstance(ev.get("progress"), dict) else {}
            status = str(progress.get("status", "unavailable"))
            if status in totals:
                totals[status] += 1
            else:
                totals["unavailable"] += 1

            active_patterns = ev.get("active_patterns", []) if isinstance(ev.get("active_patterns"), list) else []
            for p in active_patterns:
                pid = str(p.get("pattern_id", "")).strip()
                if not pid:
                    continue
                row = by_pattern[pid]
                row["pattern_id"] = pid
                row["signals"] += 1
                if status == "hit":
                    row["hits"] += 1
                    att = int(progress.get("attempts", 0) or 0)
                    if att > 0:
                        row["attempt_sum"] += att
                        row["attempt_count"] += 1
                elif status == "pending":
                    row["pending"] += 1
                else:
                    row["misses"] += 1

        patterns: List[Dict[str, Any]] = []
        for pid, row in by_pattern.items():
            signals = max(1, int(row["signals"]))
            hit_rate = row["hits"] / signals
            miss_rate = row["misses"] / signals
            avg_attempt = (row["attempt_sum"] / row["attempt_count"]) if row["attempt_count"] > 0 else 0.0
            patterns.append(
                {
                    "pattern_id": pid,
                    "signals": int(row["signals"]),
                    "hits": int(row["hits"]),
                    "misses": int(row["misses"]),
                    "pending": int(row["pending"]),
                    "hit_rate": round(hit_rate, 4),
                    "miss_rate": round(miss_rate, 4),
                    "avg_attempt_hit": round(avg_attempt, 3),
                    "recommended_multiplier": round(max(0.75, min(1.35, 0.85 + (hit_rate * 0.7))), 4),
                }
            )
        patterns.sort(key=lambda x: (-x["hit_rate"], -x["signals"], x["pattern_id"]))
        return {"totals": totals, "patterns": patterns}


pattern_telemetry = PatternTelemetryService()

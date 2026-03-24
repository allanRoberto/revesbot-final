from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


class PatternWeightProfilesService:
    """Persiste perfis de peso treinados sem alterar as definicoes base."""

    def __init__(self, base_dir: Path | None = None) -> None:
        root = Path(__file__).resolve().parent.parent
        data_dir = base_dir or (root / "data" / "pattern_weight_profiles")
        data_dir.mkdir(parents=True, exist_ok=True)
        self._profiles_dir = data_dir

    @property
    def profiles_dir(self) -> Path:
        return self._profiles_dir

    def _profile_path(self, profile_id: str) -> Path:
        safe_id = self._sanitize_profile_id(profile_id)
        return self._profiles_dir / f"{safe_id}.json"

    @staticmethod
    def _sanitize_profile_id(value: str) -> str:
        raw = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value or "").strip()).strip("-").lower()
        return raw or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

    @staticmethod
    def _build_profile_id(name: str) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        slug = PatternWeightProfilesService._sanitize_profile_id(name)
        return f"{stamp}-{slug}"

    def list_profiles(self) -> List[Dict[str, Any]]:
        profiles: List[Dict[str, Any]] = []
        for path in sorted(self._profiles_dir.glob("*.json"), reverse=True):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            weights = raw.get("weights", {})
            summary = raw.get("summary", {})
            profiles.append(
                {
                    "id": str(raw.get("id", path.stem)),
                    "name": str(raw.get("name", path.stem)),
                    "created_at": raw.get("created_at"),
                    "roulette_id": raw.get("roulette_id"),
                    "history_size": int(raw.get("history_size", 0) or 0),
                    "max_attempts": int(raw.get("max_attempts", 0) or 0),
                    "optimized_max_numbers": int(raw.get("optimized_max_numbers", 0) or 0),
                    "use_adaptive_weights": bool(raw.get("use_adaptive_weights", False)),
                    "patterns_count": len(weights) if isinstance(weights, dict) else 0,
                    "overall_hit_rate": float(summary.get("overall_hit_rate", 0.0) or 0.0),
                    "attributed_hit_rate": float(summary.get("attributed_hit_rate", 0.0) or 0.0),
                }
            )
        return profiles

    def load_profile(self, profile_id: str) -> Dict[str, Any] | None:
        path = self._profile_path(profile_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def save_profile(
        self,
        *,
        name: str,
        roulette_id: str,
        history_size: int,
        max_attempts: int,
        optimized_max_numbers: int,
        use_adaptive_weights: bool,
        config: Dict[str, Any],
        summary: Dict[str, Any],
        patterns: List[Dict[str, Any]],
        weights: Dict[str, float],
        effective_weights: Dict[str, float],
    ) -> Dict[str, Any]:
        profile_id = self._build_profile_id(name)
        payload = {
            "schema_version": "1.0.0",
            "id": profile_id,
            "name": str(name or profile_id),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "roulette_id": str(roulette_id or ""),
            "history_size": int(history_size),
            "max_attempts": int(max_attempts),
            "optimized_max_numbers": int(optimized_max_numbers),
            "use_adaptive_weights": bool(use_adaptive_weights),
            "config": dict(config or {}),
            "summary": dict(summary or {}),
            "patterns": list(patterns or []),
            "weights": {str(k): float(v) for k, v in dict(weights or {}).items()},
            "effective_weights": {str(k): float(v) for k, v in dict(effective_weights or {}).items()},
        }
        self._profile_path(profile_id).write_text(
            json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
        return payload


pattern_weight_profiles = PatternWeightProfilesService()

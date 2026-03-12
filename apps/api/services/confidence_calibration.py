from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


DEFAULT_CONFIG: Dict[str, Any] = {
    "version": "1.0.0",
    "mode": "shadow",
    "description": "Calibracao bucketizada da confidence_v2 baseada em hit@4 historico.",
    "bucket_signal_target": 150,
    "source": {
        "type": "unconfigured",
        "details": {},
    },
    "buckets": {},
}


def _bucket_label(score: float | int) -> str:
    safe_score = max(0, min(100, int(round(float(score)))))
    start = (safe_score // 10) * 10
    end = min(100, start + 9)
    return f"{start:02d}-{end:02d}"


class ConfidenceCalibrationStore:
    """Loads and applies bucket-based calibration for confidence_v2 shadow mode."""

    def __init__(self, config_path: Path | None = None) -> None:
        base_dir = Path(__file__).resolve().parent.parent
        self._config_path = config_path or (base_dir / "config" / "confidence_v2_calibration.json")
        self._config: Dict[str, Any] = copy.deepcopy(DEFAULT_CONFIG)
        self._load_config()

    def _load_config(self) -> None:
        if not self._config_path.exists():
            return
        try:
            raw = json.loads(self._config_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._config.update(raw)
        except Exception as exc:
            logger.warning("Failed to load confidence calibration config: %s", exc)

    def get_bucket(self, score: float | int) -> Dict[str, Any]:
        label = _bucket_label(score)
        buckets = self._config.get("buckets", {})
        row = buckets.get(label, {}) if isinstance(buckets, dict) else {}
        hit_rate = float(row.get("hit_rate", 0.0) or 0.0)
        reliability = float(row.get("reliability", 0.0) or 0.0)
        signals = int(row.get("signals", 0) or 0)
        return {
            "bucket": label,
            "hit_rate": max(0.0, min(1.0, hit_rate)),
            "reliability": max(0.0, min(1.0, reliability)),
            "signals": max(0, signals),
        }

    def calibrate(self, score: float | int) -> Dict[str, Any]:
        raw_score = max(0.0, min(100.0, float(score)))
        bucket = self.get_bucket(raw_score)
        reliability = float(bucket["reliability"])
        hit_rate = float(bucket["hit_rate"])
        calibrated = raw_score
        if reliability > 0.0:
            calibrated = (raw_score * (1.0 - reliability)) + ((hit_rate * 100.0) * reliability)
        calibrated = max(0, min(100, int(round(calibrated))))
        return {
            "score": calibrated,
            "bucket": bucket["bucket"],
            "hit_rate": round(hit_rate, 4),
            "reliability": round(reliability, 4),
            "signals": int(bucket["signals"]),
        }

    def get_config(self) -> Dict[str, Any]:
        return copy.deepcopy(self._config)

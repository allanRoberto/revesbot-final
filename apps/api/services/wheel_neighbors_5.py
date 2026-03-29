from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Iterable, List, Mapping

from api.services.roulette_analysis import EURO_WHEEL_ORDER, NUM2IDX


EUROPEAN_WHEEL_ORDER: tuple[int, ...] = tuple(int(n) for n in EURO_WHEEL_ORDER)
WHEEL_NEIGHBORS_5_DEFAULT_HORIZON = 8
WHEEL_NEIGHBORS_5_BASE_WEIGHT = 8.0
WHEEL_NEIGHBORS_5_DYNAMIC_WEIGHT_MIN = 0.85
WHEEL_NEIGHBORS_5_DYNAMIC_WEIGHT_MAX = 2.10
WHEEL_NEIGHBORS_5_PRIOR_STRENGTH = 25
WHEEL_NEIGHBORS_5_RECENT_WINDOW = 100
WHEEL_NEIGHBORS_5_FEEDBACK_ANCHOR_SIZE = 12
WHEEL_NEIGHBORS_5_HISTORICAL_EARLY_INDEX = 0.504969
WHEEL_NEIGHBORS_5_MAX_RESOLVED_RECORDS = 500
WHEEL_NEIGHBORS_5_PENDING_TAIL_HORIZON = 22
WHEEL_NEIGHBORS_5_PENDING_TAIL_BLEND = 0.20
WHEEL_NEIGHBORS_5_PENDING_OVERLAP_STEP = 0.12
WHEEL_NEIGHBORS_5_PENDING_OVERLAP_MAX = 0.48
WHEEL_NEIGHBORS_5_SELECTION_SIZE = 11

WHEEL_NEIGHBORS_5_HORIZON_PRIORS: Dict[int, float] = {
    6: 0.8829,
    8: 0.9440,
    10: 0.9645,
    14: 0.9935,
}

_RAW_POSITION_STATS: List[tuple[str, int, int, float]] = [
    ("left_5", -5, 187, 3.46),
    ("left_4", -4, 179, 3.51),
    ("left_3", -3, 174, 2.99),
    ("left_2", -2, 159, 3.58),
    ("left_1", -1, 190, 3.34),
    ("self", 0, 167, 3.61),
    ("right_1", 1, 183, 3.48),
    ("right_2", 2, 199, 3.12),
    ("right_3", 3, 179, 3.51),
    ("right_4", 4, 190, 3.30),
    ("right_5", 5, 189, 3.16),
]

WHEEL_NEIGHBORS_5_FIRST_HIT_ROUND_COUNTS: Dict[int, float] = {
    1: 564.0,
    2: 430.0,
    3: 313.0,
    4: 207.0,
    5: 141.0,
    6: 110.0,
    7: 69.0,
    8: 53.0,
    9: 27.0,
    10: 14.0,
    11: 28.0,
    12: 11.0,
    13: 11.0,
    14: 8.0,
    15: 1.25,
    16: 1.25,
    17: 1.25,
    18: 1.25,
    19: 1.25,
    20: 1.25,
    21: 1.25,
    22: 1.25,
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _normalize_unit_map(values: Mapping[str, float]) -> Dict[str, float]:
    if not values:
        return {}
    minimum = min(float(v) for v in values.values())
    maximum = max(float(v) for v in values.values())
    if abs(maximum - minimum) < 1e-9:
        return {str(key): 1.0 for key in values.keys()}
    return {
        str(key): (float(value) - minimum) / (maximum - minimum)
        for key, value in values.items()
    }


def _build_position_stats() -> Dict[str, Dict[str, float | int]]:
    total_hits = float(sum(item[2] for item in _RAW_POSITION_STATS))
    frequency_priors = {
        label: count / total_hits
        for label, _, count, _ in _RAW_POSITION_STATS
    }
    early_hit_raw = {
        label: 1.0 / avg_hit_round
        for label, _, _, avg_hit_round in _RAW_POSITION_STATS
    }
    normalized_frequency = _normalize_unit_map(frequency_priors)
    normalized_early = _normalize_unit_map(early_hit_raw)
    local_score_raw = {
        label: (normalized_frequency[label] * 0.65) + (normalized_early[label] * 0.35)
        for label, _, _, _ in _RAW_POSITION_STATS
    }
    normalized_local = _normalize_unit_map(local_score_raw)
    stabilized_local = {
        label: 0.15 + (float(normalized_local[label]) * 0.85)
        for label in normalized_local.keys()
    }

    stats: Dict[str, Dict[str, float | int]] = {}
    for label, offset, count, avg_hit_round in _RAW_POSITION_STATS:
        stats[label] = {
            "wheel_offset": int(offset),
            "frequency_count": int(count),
            "frequency_prior": float(frequency_priors[label]),
            "avg_hit_round": float(avg_hit_round),
            "early_hit_factor": float(early_hit_raw[label]),
            "local_score": round(float(stabilized_local[label]), 6),
        }
    return stats


WHEEL_NEIGHBORS_5_POSITION_STATS: Dict[str, Dict[str, float | int]] = _build_position_stats()

_FEEDBACK_STORES: Dict[str, "WheelNeighbors5FeedbackStore"] = {}


def resolve_wheel_neighbors_5_horizon(raw_horizon: Any) -> int:
    try:
        horizon = int(raw_horizon)
    except (TypeError, ValueError):
        horizon = WHEEL_NEIGHBORS_5_DEFAULT_HORIZON
    if horizon in WHEEL_NEIGHBORS_5_HORIZON_PRIORS:
        return horizon
    return WHEEL_NEIGHBORS_5_DEFAULT_HORIZON


def get_wheel_neighbors_5_window(base_number: int, window: int = 5) -> List[int]:
    base = int(base_number)
    if base not in NUM2IDX:
        return []
    safe_window = max(1, int(window))
    idx = int(NUM2IDX[base])
    wheel_size = len(EUROPEAN_WHEEL_ORDER)
    return [
        int(EUROPEAN_WHEEL_ORDER[(idx + offset) % wheel_size])
        for offset in range(-safe_window, safe_window + 1)
    ]


def build_wheel_neighbors_5_candidate_map(base_number: int) -> Dict[str, Any]:
    ordered_candidates = get_wheel_neighbors_5_window(base_number, window=5)
    if len(ordered_candidates) != 11:
        return {
            "base_number": int(base_number),
            "ordered_candidates": [],
            "candidate_positions": {},
            "candidate_details": {},
            "position_priors": copy.deepcopy(WHEEL_NEIGHBORS_5_POSITION_STATS),
        }

    candidate_positions: Dict[str, Dict[str, int | str]] = {}
    candidate_details: Dict[str, Dict[str, float | int | str]] = {}
    position_sequence = list(WHEEL_NEIGHBORS_5_POSITION_STATS.keys())

    for position_label, number in zip(position_sequence, ordered_candidates):
        stats = WHEEL_NEIGHBORS_5_POSITION_STATS[position_label]
        detail = {
            "position": str(position_label),
            "wheel_offset": int(stats["wheel_offset"]),
            "frequency_prior": round(float(stats["frequency_prior"]), 6),
            "avg_hit_round": round(float(stats["avg_hit_round"]), 4),
            "early_hit_factor": round(float(stats["early_hit_factor"]), 6),
            "local_score": round(float(stats["local_score"]), 6),
        }
        candidate_positions[str(number)] = {
            "position": str(position_label),
            "wheel_offset": int(stats["wheel_offset"]),
        }
        candidate_details[str(number)] = detail

    return {
        "base_number": int(base_number),
        "ordered_candidates": [int(n) for n in ordered_candidates],
        "candidate_positions": candidate_positions,
        "candidate_details": candidate_details,
        "position_priors": copy.deepcopy(WHEEL_NEIGHBORS_5_POSITION_STATS),
    }


def _first_hit_mass(max_round: int) -> float:
    safe_round = max(0, int(max_round))
    return float(
        sum(
            float(count)
            for round_no, count in WHEEL_NEIGHBORS_5_FIRST_HIT_ROUND_COUNTS.items()
            if int(round_no) <= safe_round
        )
    )


def _remaining_hit_mass(age: int, max_round: int) -> float:
    safe_age = max(0, int(age))
    safe_round = max(0, int(max_round))
    if safe_age >= safe_round:
        return 0.0
    return float(
        sum(
            float(count)
            for round_no, count in WHEEL_NEIGHBORS_5_FIRST_HIT_ROUND_COUNTS.items()
            if safe_age < int(round_no) <= safe_round
        )
    )


def _build_pending_age_weights(age: int, horizon_used: int) -> Dict[str, float]:
    safe_age = max(0, int(age))
    safe_horizon = resolve_wheel_neighbors_5_horizon(horizon_used)
    operational_total = _first_hit_mass(safe_horizon)
    operational_remaining = _remaining_hit_mass(safe_age, safe_horizon)
    tail_total = _first_hit_mass(WHEEL_NEIGHBORS_5_PENDING_TAIL_HORIZON)
    tail_remaining = _remaining_hit_mass(safe_age, WHEEL_NEIGHBORS_5_PENDING_TAIL_HORIZON)

    operational_weight = (
        float(operational_remaining) / float(operational_total)
        if operational_total > 0
        else 0.0
    )
    tail_weight = (
        float(tail_remaining) / float(tail_total)
        if tail_total > 0
        else 0.0
    )
    combined_weight = (
        ((1.0 - float(WHEEL_NEIGHBORS_5_PENDING_TAIL_BLEND)) * float(operational_weight))
        + (float(WHEEL_NEIGHBORS_5_PENDING_TAIL_BLEND) * float(tail_weight))
    )
    return {
        "operational_weight": round(float(operational_weight), 6),
        "tail_weight": round(float(tail_weight), 6),
        "combined_weight": round(float(combined_weight), 6),
    }


def build_wheel_neighbors_5_pending_state(
    *,
    history: Iterable[int],
    horizon_used: Any = None,
    latest_base_number: int | None = None,
) -> Dict[str, Any]:
    safe_history = [int(n) for n in history if 0 <= int(n) <= 36]
    safe_horizon = resolve_wheel_neighbors_5_horizon(horizon_used)
    if not safe_history:
        return {
            "history_depth": 0,
            "history_order_assumed": "newest_first",
            "horizon_used": int(safe_horizon),
            "pending_bases": [],
            "pending_activations": [],
            "resolved_activations": [],
        }

    chronological = list(reversed(safe_history))
    newest_override = int(latest_base_number) if latest_base_number in NUM2IDX else None
    pending_activations: List[Dict[str, Any]] = []
    resolved_activations: List[Dict[str, Any]] = []
    last_sequence_index = len(chronological) - 1

    for sequence_index, spin_value in enumerate(chronological):
        current_spin = int(spin_value)
        remaining_pending: List[Dict[str, Any]] = []
        for activation in pending_activations:
            if current_spin in {
                int(number)
                for number in activation.get("ordered_candidates", [])
            }:
                hit_meta = activation.get("candidate_details", {}).get(str(current_spin), {})
                resolved_activations.append(
                    {
                        "activation_id": str(activation.get("activation_id", "")),
                        "base_number": int(activation.get("base_number", current_spin)),
                        "resolved_by_number": int(current_spin),
                        "hit_round": int(sequence_index - int(activation.get("sequence_index", sequence_index))),
                        "hit_position": str(hit_meta.get("position", "")) or None,
                        "resolved_sequence_index": int(sequence_index),
                    }
                )
            else:
                remaining_pending.append(activation)
        pending_activations = remaining_pending

        activation_base = int(current_spin)
        if newest_override is not None and sequence_index == last_sequence_index:
            activation_base = int(newest_override)

        candidate_map = build_wheel_neighbors_5_candidate_map(activation_base)
        if not candidate_map.get("ordered_candidates"):
            continue

        pending_activations.append(
            {
                "activation_id": f"live::{sequence_index}::{activation_base}",
                "base_number": int(activation_base),
                "source_spin": int(current_spin),
                "sequence_index": int(sequence_index),
                "ordered_candidates": [int(n) for n in candidate_map.get("ordered_candidates", [])],
                "candidate_positions": copy.deepcopy(candidate_map.get("candidate_positions", {})),
                "candidate_details": copy.deepcopy(candidate_map.get("candidate_details", {})),
            }
        )

    live_pending: List[Dict[str, Any]] = []
    for activation in pending_activations:
        pending_age = int(last_sequence_index - int(activation.get("sequence_index", last_sequence_index)))
        age_weights = _build_pending_age_weights(pending_age, safe_horizon)
        live_pending.append(
            {
                "activation_id": str(activation.get("activation_id", "")),
                "base_number": int(activation.get("base_number", 0)),
                "source_spin": int(activation.get("source_spin", 0)),
                "sequence_index": int(activation.get("sequence_index", 0)),
                "pending_age": int(pending_age),
                "age_weight": float(age_weights["combined_weight"]),
                "operational_age_weight": float(age_weights["operational_weight"]),
                "tail_age_weight": float(age_weights["tail_weight"]),
                "ordered_candidates": [int(n) for n in activation.get("ordered_candidates", [])],
                "candidate_positions": copy.deepcopy(activation.get("candidate_positions", {})),
                "candidate_details": copy.deepcopy(activation.get("candidate_details", {})),
            }
        )

    live_pending.sort(key=lambda item: (-int(item["pending_age"]), int(item["sequence_index"])))

    return {
        "history_depth": len(safe_history),
        "history_order_assumed": "newest_first",
        "horizon_used": int(safe_horizon),
        "pending_bases": [int(item["base_number"]) for item in live_pending],
        "pending_activations": live_pending,
        "resolved_activations": resolved_activations,
    }


def build_wheel_neighbors_5_pending_candidate_scores(
    *,
    history: Iterable[int],
    horizon_used: Any = None,
    latest_base_number: int | None = None,
    selection_size: int = WHEEL_NEIGHBORS_5_SELECTION_SIZE,
) -> Dict[str, Any]:
    pending_state = build_wheel_neighbors_5_pending_state(
        history=history,
        horizon_used=horizon_used,
        latest_base_number=latest_base_number,
    )
    pending_activations = list(pending_state.get("pending_activations", []))
    if not pending_activations:
        return {
            "pending_state": pending_state,
            "selected_numbers": [],
            "scores": {},
            "candidate_details": {},
            "candidate_ranking": [],
        }

    aggregate: Dict[int, Dict[str, Any]] = {}
    for activation in pending_activations:
        base_number = int(activation.get("base_number", 0))
        pending_age = int(activation.get("pending_age", 0))
        age_weight = float(activation.get("age_weight", 0.0) or 0.0)
        for number_str, detail in dict(activation.get("candidate_details", {})).items():
            number = int(number_str)
            local_score = float(detail.get("local_score", 0.0) or 0.0)
            contribution = round(local_score * age_weight, 6)
            item = aggregate.setdefault(
                number,
                {
                    "candidate_number": int(number),
                    "raw_pending_pressure": 0.0,
                    "latest_base_component": 0.0,
                    "overlap_count": 0,
                    "supporting_bases": [],
                },
            )
            item["raw_pending_pressure"] = round(float(item["raw_pending_pressure"]) + float(contribution), 6)
            item["overlap_count"] = int(item["overlap_count"]) + 1
            item["supporting_bases"].append(
                {
                    "base_number": int(base_number),
                    "pending_age": int(pending_age),
                    "age_weight": round(float(age_weight), 6),
                    "position": str(detail.get("position", "")),
                    "wheel_offset": int(detail.get("wheel_offset", 0)),
                    "contribution": round(float(contribution), 6),
                }
            )
            if latest_base_number is not None and int(base_number) == int(latest_base_number):
                item["latest_base_component"] = round(
                    float(item["latest_base_component"]) + float(contribution),
                    6,
                )

    raw_totals: Dict[str, float] = {}
    for number, item in aggregate.items():
        overlap_bonus = 1.0 + min(
            float(WHEEL_NEIGHBORS_5_PENDING_OVERLAP_MAX),
            max(0, int(item["overlap_count"]) - 1) * float(WHEEL_NEIGHBORS_5_PENDING_OVERLAP_STEP),
        )
        item["supporting_bases"] = sorted(
            list(item["supporting_bases"]),
            key=lambda row: (-int(row["pending_age"]), int(row["base_number"])),
        )
        item["overlap_bonus"] = round(float(overlap_bonus), 6)
        item["raw_total"] = round(float(item["raw_pending_pressure"]) * float(overlap_bonus), 6)
        raw_totals[str(number)] = float(item["raw_total"])

    normalized_totals = _normalize_unit_map(raw_totals)
    for number, item in aggregate.items():
        normalized_score = float(normalized_totals.get(str(number), 0.0))
        item["local_score"] = round(0.15 + (normalized_score * 0.85), 6)
        item["supporting_base_numbers"] = [int(row["base_number"]) for row in item["supporting_bases"]]

    ranked_items = sorted(
        aggregate.values(),
        key=lambda row: (
            -float(row["local_score"]),
            -int(row["overlap_count"]),
            -float(row["latest_base_component"]),
            int(row["candidate_number"]),
        ),
    )
    top_size = max(1, int(selection_size))
    selected_items = ranked_items[:top_size]
    selected_numbers = [int(item["candidate_number"]) for item in selected_items]

    return {
        "pending_state": pending_state,
        "selected_numbers": selected_numbers,
        "scores": {
            int(item["candidate_number"]): round(float(item["local_score"]), 6)
            for item in selected_items
        },
        "candidate_details": {
            str(int(item["candidate_number"])): copy.deepcopy(item)
            for item in ranked_items
        },
        "candidate_ranking": [int(item["candidate_number"]) for item in ranked_items],
    }


def compute_wheel_neighbors_5_dynamic_multiplier(
    *,
    recent_total: int,
    recent_hits: int,
    recent_hit_count: int,
    recent_early_sum: float,
    expected_hit_rate: float,
    historical_early_index: float = WHEEL_NEIGHBORS_5_HISTORICAL_EARLY_INDEX,
    prior_strength: float = WHEEL_NEIGHBORS_5_PRIOR_STRENGTH,
    minimum: float = WHEEL_NEIGHBORS_5_DYNAMIC_WEIGHT_MIN,
    maximum: float = WHEEL_NEIGHBORS_5_DYNAMIC_WEIGHT_MAX,
) -> Dict[str, float]:
    prior_mean = _clamp(float(expected_hit_rate), 1e-6, 1.0)
    prior_hits = float(prior_strength) * prior_mean
    smoothed_hit_rate = (float(recent_hits) + prior_hits) / (float(recent_total) + float(prior_strength))
    smoothed_early_index = (
        float(recent_early_sum) + (float(prior_strength) * float(historical_early_index))
    ) / (float(recent_hit_count) + float(prior_strength))

    # Centro neutro em 1.0 para não inflar o padrão quando ele só está na média histórica.
    raw_multiplier = (
        1.0
        + (0.75 * ((smoothed_hit_rate / prior_mean) - 1.0))
        + (0.25 * ((smoothed_early_index / float(historical_early_index)) - 1.0))
    )
    dynamic_multiplier = _clamp(raw_multiplier, float(minimum), float(maximum))

    return {
        "prior_mean": round(prior_mean, 6),
        "smoothed_hit_rate": round(float(smoothed_hit_rate), 6),
        "smoothed_early_index": round(float(smoothed_early_index), 6),
        "dynamic_multiplier": round(float(dynamic_multiplier), 6),
    }


class WheelNeighbors5FeedbackStore:
    def __init__(self, storage_path: Path | None = None) -> None:
        base_dir = Path(__file__).resolve().parent.parent
        data_dir = base_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        self._storage_path = storage_path or (data_dir / "wheel_neighbors_5_feedback.json")
        self._lock = RLock()
        self._state: Dict[str, Any] = {
            "schema_version": "1.0.0",
            "pending": [],
            "resolved": [],
        }
        self._load()

    @property
    def storage_path(self) -> Path:
        return self._storage_path

    def _load(self) -> None:
        with self._lock:
            if not self._storage_path.exists():
                return
            try:
                raw = json.loads(self._storage_path.read_text(encoding="utf-8"))
            except Exception:
                return
            if isinstance(raw, dict):
                pending = raw.get("pending", [])
                resolved = raw.get("resolved", [])
                self._state = {
                    "schema_version": str(raw.get("schema_version", "1.0.0")),
                    "pending": list(pending) if isinstance(pending, list) else [],
                    "resolved": list(resolved) if isinstance(resolved, list) else [],
                }

    def _save(self) -> None:
        self._storage_path.write_text(
            json.dumps(self._state, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )

    def clear(self) -> None:
        with self._lock:
            self._state = {
                "schema_version": "1.0.0",
                "pending": [],
                "resolved": [],
            }
            self._save()

    @staticmethod
    def _history_anchor(history: Iterable[int], anchor_size: int) -> List[int]:
        return [int(n) for n in list(history)[: max(1, int(anchor_size))] if 0 <= int(n) <= 36]

    @staticmethod
    def _activation_key(
        *,
        base_number: int,
        horizon_used: int,
        ordered_candidates: List[int],
        history_anchor: List[int],
    ) -> str:
        raw = "|".join(
            [
                str(int(base_number)),
                str(int(horizon_used)),
                ",".join(str(int(n)) for n in ordered_candidates),
                ",".join(str(int(n)) for n in history_anchor),
            ]
        )
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _find_anchor_offset(history: List[int], anchor: List[int]) -> int | None:
        if not anchor or len(anchor) > len(history):
            return None
        anchor_len = len(anchor)
        last_start = len(history) - anchor_len
        for start in range(0, last_start + 1):
            if history[start:start + anchor_len] == anchor:
                return start
        return None

    def register_activation(
        self,
        *,
        base_number: int,
        ordered_candidates: List[int],
        candidate_positions: Mapping[str, Mapping[str, Any]],
        horizon_used: int,
        expected_hit_rate: float,
        history_anchor: List[int],
        recent_snapshot: Mapping[str, Any],
    ) -> Dict[str, Any]:
        if not history_anchor or not ordered_candidates:
            return {}

        activation_key = self._activation_key(
            base_number=int(base_number),
            horizon_used=int(horizon_used),
            ordered_candidates=[int(n) for n in ordered_candidates],
            history_anchor=[int(n) for n in history_anchor],
        )

        with self._lock:
            for item in self._state["pending"]:
                if str(item.get("activation_id", "")) == activation_key:
                    return copy.deepcopy(item)
            for item in self._state["resolved"]:
                if str(item.get("activation_id", "")) == activation_key:
                    return copy.deepcopy(item)

            activation = {
                "activation_id": activation_key,
                "created_at": _utc_now_iso(),
                "base_number": int(base_number),
                "ordered_candidates": [int(n) for n in ordered_candidates],
                "candidate_positions": {
                    str(number): {
                        "position": str(meta.get("position", "")),
                        "wheel_offset": int(meta.get("wheel_offset", 0)),
                    }
                    for number, meta in candidate_positions.items()
                },
                "horizon_used": int(horizon_used),
                "expected_hit_rate": round(float(expected_hit_rate), 6),
                "history_anchor": [int(n) for n in history_anchor],
                "status": "pending",
                "resolved_at": None,
                "hit": None,
                "hit_round": None,
                "hit_number": None,
                "hit_position": None,
                "recent_snapshot_at_activation": {
                    "recent_sample_size": int(recent_snapshot.get("recent_sample_size", 0) or 0),
                    "recent_hit_rate": float(recent_snapshot.get("recent_hit_rate", 0.0) or 0.0),
                    "recent_mean_hit_round": recent_snapshot.get("recent_mean_hit_round"),
                },
            }
            self._state["pending"].append(activation)
            self._save()
            return copy.deepcopy(activation)

    def resolve_from_history(self, *, history: List[int]) -> List[Dict[str, Any]]:
        safe_history = [int(n) for n in history if 0 <= int(n) <= 36]
        if not safe_history:
            return []

        resolved_items: List[Dict[str, Any]] = []
        with self._lock:
            pending_items = list(self._state["pending"])
            remaining_pending: List[Dict[str, Any]] = []
            for item in pending_items:
                anchor = [int(n) for n in item.get("history_anchor", []) if 0 <= int(n) <= 36]
                offset = self._find_anchor_offset(safe_history, anchor)
                if offset is None or offset <= 0:
                    remaining_pending.append(item)
                    continue

                horizon_used = max(1, int(item.get("horizon_used", WHEEL_NEIGHBORS_5_DEFAULT_HORIZON)))
                candidate_set = {int(n) for n in item.get("ordered_candidates", [])}
                candidate_positions = item.get("candidate_positions", {})
                hit_number = None
                hit_round = None
                hit_position = None
                for step in range(1, min(offset, horizon_used) + 1):
                    value = int(safe_history[offset - step])
                    if value in candidate_set:
                        hit_number = int(value)
                        hit_round = int(step)
                        hit_meta = candidate_positions.get(str(value), {})
                        hit_position = str(hit_meta.get("position", "")) or None
                        break

                if hit_round is None and offset < horizon_used:
                    remaining_pending.append(item)
                    continue

                resolved = dict(item)
                resolved["status"] = "hit" if hit_round is not None else "miss"
                resolved["resolved_at"] = _utc_now_iso()
                resolved["hit"] = bool(hit_round is not None)
                resolved["hit_round"] = int(hit_round) if hit_round is not None else None
                resolved["hit_number"] = int(hit_number) if hit_number is not None else None
                resolved["hit_position"] = hit_position
                self._state["resolved"].append(resolved)
                resolved_items.append(copy.deepcopy(resolved))

            self._state["pending"] = remaining_pending
            self._trim_resolved_locked()
            if resolved_items:
                self._save()
        return resolved_items

    def _trim_resolved_locked(self) -> None:
        sorted_items = sorted(
            self._state["resolved"],
            key=lambda row: str(row.get("resolved_at") or row.get("created_at") or ""),
            reverse=True,
        )
        self._state["resolved"] = sorted_items[:WHEEL_NEIGHBORS_5_MAX_RESOLVED_RECORDS]

    def recent_performance_snapshot(
        self,
        *,
        horizon_used: int,
        window_size: int = WHEEL_NEIGHBORS_5_RECENT_WINDOW,
    ) -> Dict[str, Any]:
        safe_window = max(1, int(window_size))
        safe_horizon = resolve_wheel_neighbors_5_horizon(horizon_used)

        with self._lock:
            resolved = [
                dict(item)
                for item in self._state["resolved"]
                if int(item.get("horizon_used", WHEEL_NEIGHBORS_5_DEFAULT_HORIZON)) == safe_horizon
            ]

        resolved.sort(
            key=lambda row: str(row.get("resolved_at") or row.get("created_at") or ""),
            reverse=True,
        )
        recent = resolved[:safe_window]
        recent_hits = [item for item in recent if bool(item.get("hit", False))]
        hit_rounds = [
            int(item["hit_round"])
            for item in recent_hits
            if isinstance(item.get("hit_round"), int) and int(item["hit_round"]) > 0
        ]
        recent_sample_size = len(recent)
        recent_hit_count = len(hit_rounds)
        recent_early_sum = sum(1.0 / int(round_no) for round_no in hit_rounds)

        return {
            "available": recent_sample_size > 0,
            "window_size": safe_window,
            "recent_sample_size": int(recent_sample_size),
            "recent_hits": int(len(recent_hits)),
            "recent_hit_rate": round(len(recent_hits) / recent_sample_size, 6) if recent_sample_size else 0.0,
            "recent_mean_hit_round": round(sum(hit_rounds) / recent_hit_count, 4) if recent_hit_count else None,
            "recent_early_index": round(recent_early_sum / recent_hit_count, 6) if recent_hit_count else 0.0,
            "recent_early_sum": round(float(recent_early_sum), 6),
            "recent_hit_count": int(recent_hit_count),
            "resolved_cases": recent,
        }


def get_wheel_neighbors_5_feedback_store(storage_path: str | Path | None = None) -> WheelNeighbors5FeedbackStore:
    resolved_path = str(Path(storage_path).resolve()) if storage_path else "__default__"
    store = _FEEDBACK_STORES.get(resolved_path)
    if store is None:
        store = WheelNeighbors5FeedbackStore(Path(storage_path) if storage_path else None)
        _FEEDBACK_STORES[resolved_path] = store
    return store


def build_wheel_neighbors_5_result(
    *,
    base_number: int,
    requested_horizon: Any = None,
    recent_window_size: int = WHEEL_NEIGHBORS_5_RECENT_WINDOW,
    base_weight: float = WHEEL_NEIGHBORS_5_BASE_WEIGHT,
    feedback_storage_path: str | Path | None = None,
    history: Iterable[int] | None = None,
) -> Dict[str, Any]:
    safe_base = int(base_number)
    if safe_base not in NUM2IDX:
        return {
            "numbers": [],
            "scores": {},
            "dynamic_multiplier": 1.0,
            "meta": {
                "pattern": "wheel_neighbors_5",
                "base_number": safe_base,
                "error": "invalid_base_number",
            },
        }

    horizon_used = resolve_wheel_neighbors_5_horizon(requested_horizon)
    expected_hit_rate = float(WHEEL_NEIGHBORS_5_HORIZON_PRIORS[horizon_used])
    candidate_map = build_wheel_neighbors_5_candidate_map(safe_base)
    ordered_candidates = [int(n) for n in candidate_map["ordered_candidates"]]
    safe_history = [int(n) for n in history if 0 <= int(n) <= 36] if history is not None else [safe_base]
    if not safe_history:
        safe_history = [safe_base]
    pending_scores = build_wheel_neighbors_5_pending_candidate_scores(
        history=safe_history,
        horizon_used=horizon_used,
        latest_base_number=safe_base,
        selection_size=WHEEL_NEIGHBORS_5_SELECTION_SIZE,
    )
    selected_numbers = [int(n) for n in pending_scores.get("selected_numbers", [])]
    aggregated_candidate_details = {
        str(number): dict(detail)
        for number, detail in pending_scores.get("candidate_details", {}).items()
    }
    scores = {
        int(number): round(float(score), 6)
        for number, score in pending_scores.get("scores", {}).items()
    }
    if not selected_numbers:
        selected_numbers = [int(n) for n in ordered_candidates]
        scores = {
            int(number): round(float(details["local_score"]), 6)
            for number, details in candidate_map["candidate_details"].items()
        }

    feedback_snapshot = {
        "available": False,
        "window_size": max(1, int(recent_window_size)),
        "recent_sample_size": 0,
        "recent_hits": 0,
        "recent_hit_rate": 0.0,
        "recent_mean_hit_round": None,
        "recent_early_index": 0.0,
        "recent_early_sum": 0.0,
        "recent_hit_count": 0,
    }
    dynamic = {
        "prior_mean": round(expected_hit_rate, 6),
        "smoothed_hit_rate": round(expected_hit_rate, 6),
        "smoothed_early_index": round(WHEEL_NEIGHBORS_5_HISTORICAL_EARLY_INDEX, 6),
        "dynamic_multiplier": 1.0,
    }
    feedback_store = get_wheel_neighbors_5_feedback_store(feedback_storage_path)
    feedback_snapshot = feedback_store.recent_performance_snapshot(
        horizon_used=horizon_used,
        window_size=max(1, int(recent_window_size)),
    )
    dynamic = compute_wheel_neighbors_5_dynamic_multiplier(
        recent_total=int(feedback_snapshot.get("recent_sample_size", 0) or 0),
        recent_hits=int(feedback_snapshot.get("recent_hits", 0) or 0),
        recent_hit_count=int(feedback_snapshot.get("recent_hit_count", 0) or 0),
        recent_early_sum=float(feedback_snapshot.get("recent_early_sum", 0.0) or 0.0),
        expected_hit_rate=expected_hit_rate,
    )

    candidate_details = copy.deepcopy(candidate_map["candidate_details"])
    for number, detail in candidate_details.items():
        detail["final_contribution"] = round(
            float(detail["local_score"]) * float(base_weight) * float(dynamic["dynamic_multiplier"]),
            6,
        )
    for number, detail in aggregated_candidate_details.items():
        detail["selected"] = int(number) in set(selected_numbers)
        detail["final_contribution"] = round(
            float(detail.get("local_score", 0.0)) * float(base_weight) * float(dynamic["dynamic_multiplier"]),
            6,
        )

    pending_state = dict(pending_scores.get("pending_state", {}))
    pending_activations = list(pending_state.get("pending_activations", []))
    resolved_activations = list(pending_state.get("resolved_activations", []))

    meta = {
        "pattern": "wheel_neighbors_5",
        "base_number": int(safe_base),
        "wheel_window": 5,
        "ordered_candidates": ordered_candidates,
        "candidate_positions": candidate_map["candidate_positions"],
        "position_priors": copy.deepcopy(WHEEL_NEIGHBORS_5_POSITION_STATS),
        "early_hit_bias": {
            label: round(float(stats["early_hit_factor"]), 6)
            for label, stats in WHEEL_NEIGHBORS_5_POSITION_STATS.items()
        },
        "candidate_details": candidate_details,
        "aggregated_candidate_ranking": [int(n) for n in pending_scores.get("candidate_ranking", [])],
        "aggregated_candidate_details": aggregated_candidate_details,
        "selected_numbers": [int(n) for n in selected_numbers],
        "pending_bases": [int(item.get("base_number", 0)) for item in pending_activations],
        "pending_base_details": pending_activations,
        "resolved_pending_bases": resolved_activations[-12:],
        "horizon_config_used": {
            "supported_horizons": sorted(WHEEL_NEIGHBORS_5_HORIZON_PRIORS.keys()),
            "horizon_used": int(horizon_used),
            "expected_hit_rate": round(expected_hit_rate, 6),
        },
        "recent_performance_snapshot": {
            key: value
            for key, value in feedback_snapshot.items()
            if key != "resolved_cases"
        },
        "dynamic_weight_used": round(float(dynamic["dynamic_multiplier"]), 6),
        "dynamic_weight_details": dynamic,
        "base_weight": round(float(base_weight), 6),
        "final_pattern_confidence": round(
            _clamp(expected_hit_rate * float(dynamic["dynamic_multiplier"]), 0.0, 1.0),
            6,
        ),
    }

    return {
        "numbers": [int(n) for n in selected_numbers],
        "scores": scores,
        "dynamic_multiplier": float(dynamic["dynamic_multiplier"]),
        "meta": meta,
        "explanation": (
            f"Wheel neighbors 5 ativo a partir do numero {safe_base} "
            f"com {len(pending_activations)} base(s) pendente(s) e horizonte {horizon_used}."
        ),
    }


__all__ = [
    "EUROPEAN_WHEEL_ORDER",
    "WHEEL_NEIGHBORS_5_BASE_WEIGHT",
    "WHEEL_NEIGHBORS_5_DEFAULT_HORIZON",
    "WHEEL_NEIGHBORS_5_DYNAMIC_WEIGHT_MAX",
    "WHEEL_NEIGHBORS_5_DYNAMIC_WEIGHT_MIN",
    "WHEEL_NEIGHBORS_5_FEEDBACK_ANCHOR_SIZE",
    "WHEEL_NEIGHBORS_5_FIRST_HIT_ROUND_COUNTS",
    "WHEEL_NEIGHBORS_5_HISTORICAL_EARLY_INDEX",
    "WHEEL_NEIGHBORS_5_HORIZON_PRIORS",
    "WHEEL_NEIGHBORS_5_PENDING_OVERLAP_MAX",
    "WHEEL_NEIGHBORS_5_PENDING_OVERLAP_STEP",
    "WHEEL_NEIGHBORS_5_PENDING_TAIL_BLEND",
    "WHEEL_NEIGHBORS_5_PENDING_TAIL_HORIZON",
    "WHEEL_NEIGHBORS_5_POSITION_STATS",
    "WHEEL_NEIGHBORS_5_PRIOR_STRENGTH",
    "WHEEL_NEIGHBORS_5_RECENT_WINDOW",
    "WHEEL_NEIGHBORS_5_SELECTION_SIZE",
    "WheelNeighbors5FeedbackStore",
    "build_wheel_neighbors_5_candidate_map",
    "build_wheel_neighbors_5_pending_candidate_scores",
    "build_wheel_neighbors_5_pending_state",
    "build_wheel_neighbors_5_result",
    "compute_wheel_neighbors_5_dynamic_multiplier",
    "get_wheel_neighbors_5_feedback_store",
    "get_wheel_neighbors_5_window",
    "resolve_wheel_neighbors_5_horizon",
]

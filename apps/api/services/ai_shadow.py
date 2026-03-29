from __future__ import annotations

import copy
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from api.core.db import history_coll
from api.services import decoder_lab
from api.services.roulette_analysis import NUM2IDX, WHEEL_SIZE
from api.services.wheel_neighbors_5 import (
    build_wheel_neighbors_5_pending_candidate_scores,
    get_wheel_neighbors_5_window,
)


AI_SHADOW_DEFAULT_STATE_WINDOW = 6
AI_SHADOW_DEFAULT_FUTURE_HORIZON = 5
AI_SHADOW_DEFAULT_DAYS_BACK = 30
AI_SHADOW_DEFAULT_MAX_RECORDS = 5000
AI_SHADOW_DEFAULT_DECODER_TOP_K = 18
AI_SHADOW_DEFAULT_TOP_K = 12
AI_SHADOW_DEFAULT_EPISODE_LIMIT = 80
AI_SHADOW_DEFAULT_SIMILARITY_THRESHOLD = 0.54
AI_SHADOW_DEFAULT_VALIDATION_RATIO = 0.25
AI_SHADOW_DEFAULT_MIN_SUPPORT = 3
AI_SHADOW_DEFAULT_MIN_CONFIDENCE = 56
AI_SHADOW_DEFAULT_MIN_MATCHED_EPISODES = 12
AI_SHADOW_DEFAULT_LEARNING_RATE = 0.18
AI_SHADOW_PROFILE_WEIGHT_LIMIT = 3.5
AI_SHADOW_RECENT_WINDOW = 18
AI_SHADOW_SLEEP_CAP = 24

AI_SHADOW_FEATURE_NAMES: tuple[str, ...] = (
    "decoder_score",
    "decoder_rank",
    "transition_rate",
    "pending_pressure",
    "wheel_neighbor",
    "hotspot_proximity",
    "recent_frequency",
    "sleep_score",
    "freshness",
    "terminal_bias",
)

AI_SHADOW_DEFAULT_WEIGHTS: Dict[str, float] = {
    "bias": -1.05,
    "decoder_score": 1.35,
    "decoder_rank": 0.78,
    "transition_rate": 0.92,
    "pending_pressure": 1.12,
    "wheel_neighbor": 0.64,
    "hotspot_proximity": 0.48,
    "recent_frequency": 0.22,
    "sleep_score": 0.38,
    "freshness": 0.27,
    "terminal_bias": 0.18,
}


def _coerce_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise TypeError(f"Timestamp inválido para ai_shadow: {value!r}")


def _normalize_rows(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for row in rows:
        if "value" not in row or "timestamp" not in row:
            continue
        try:
            value = int(row["value"])
        except (TypeError, ValueError):
            continue
        if not (0 <= value <= 36):
            continue
        normalized.append(
            {
                "value": value,
                "timestamp": _coerce_timestamp(row["timestamp"]),
            }
        )
    normalized.sort(key=lambda item: item["timestamp"])
    return normalized


def _sigmoid(value: float) -> float:
    if value >= 0:
        exp = math.exp(-value)
        return 1.0 / (1.0 + exp)
    exp = math.exp(value)
    return exp / (1.0 + exp)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _normalize_float_map(values: Mapping[int, float]) -> Dict[int, float]:
    if not values:
        return {}
    minimum = min(float(v) for v in values.values())
    maximum = max(float(v) for v in values.values())
    if abs(maximum - minimum) < 1e-9:
        return {int(key): (1.0 if maximum > 0 else 0.0) for key in values.keys()}
    spread = maximum - minimum
    return {int(key): (float(value) - minimum) / spread for key, value in values.items()}


def _circular_distance(a_idx: int, b_idx: int) -> int:
    raw = abs(a_idx - b_idx)
    return min(raw, WHEEL_SIZE - raw)


def _build_default_profile(roulette_id: str) -> Dict[str, Any]:
    return {
        "roulette_id": roulette_id,
        "weights": dict(AI_SHADOW_DEFAULT_WEIGHTS),
        "signals": 0,
        "wins": 0,
        "losses": 0,
        "recent_outcomes": [],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


class AIShadowProfileStore:
    def __init__(self, storage_path: str | Path | None = None, feedback_log_path: str | Path | None = None) -> None:
        data_dir = Path(__file__).resolve().parent.parent / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        self._storage_path = Path(storage_path) if storage_path else (data_dir / "ai_shadow_profiles.json")
        self._feedback_log_path = Path(feedback_log_path) if feedback_log_path else (data_dir / "ai_shadow_feedback.jsonl")
        self._lock = RLock()

    def _load(self) -> Dict[str, Any]:
        if not self._storage_path.exists():
            return {"profiles": {}}
        try:
            return json.loads(self._storage_path.read_text(encoding="utf-8"))
        except Exception:
            return {"profiles": {}}

    def _save(self, payload: Dict[str, Any]) -> None:
        self._storage_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_profile(self, roulette_id: str) -> Dict[str, Any]:
        safe_roulette = str(roulette_id or "").strip()
        with self._lock:
            payload = self._load()
            profiles = payload.setdefault("profiles", {})
            profile = profiles.get(safe_roulette)
            if not isinstance(profile, dict):
                profile = _build_default_profile(safe_roulette)
                profiles[safe_roulette] = profile
                self._save(payload)
            else:
                merged = _build_default_profile(safe_roulette)
                merged.update(profile)
                merged["weights"] = {**AI_SHADOW_DEFAULT_WEIGHTS, **dict(profile.get("weights") or {})}
                merged["recent_outcomes"] = list(profile.get("recent_outcomes") or [])[-50:]
                profile = merged
                profiles[safe_roulette] = profile
                self._save(payload)
            return copy.deepcopy(profile)

    def apply_feedback(
        self,
        *,
        roulette_id: str,
        signal_id: str,
        feature_map: Mapping[str, Mapping[str, float]],
        candidate_numbers: Sequence[int],
        hit_number: int | None,
        status: str,
        confidence_score: int = 0,
        matched_episodes: int = 0,
        avg_similarity: float = 0.0,
        attempts: int = 0,
        max_attempts: int = 0,
    ) -> Dict[str, Any]:
        safe_roulette = str(roulette_id or "").strip()
        safe_status = str(status or "").strip().lower() or "loss"
        safe_hit = int(hit_number) if isinstance(hit_number, int) else None
        with self._lock:
            payload = self._load()
            profiles = payload.setdefault("profiles", {})
            profile = profiles.get(safe_roulette) or _build_default_profile(safe_roulette)
            weights = {**AI_SHADOW_DEFAULT_WEIGHTS, **dict(profile.get("weights") or {})}
            signals = int(profile.get("signals") or 0)
            learning_rate = AI_SHADOW_DEFAULT_LEARNING_RATE / math.sqrt(max(1, signals + 1))
            learning_rate = _clamp(learning_rate, 0.02, AI_SHADOW_DEFAULT_LEARNING_RATE)

            for number in candidate_numbers:
                features = dict(feature_map.get(str(int(number))) or {})
                if not features:
                    continue
                linear = float(weights.get("bias", 0.0))
                for feature_name in AI_SHADOW_FEATURE_NAMES:
                    linear += float(weights.get(feature_name, 0.0)) * float(features.get(feature_name, 0.0))
                prediction = _sigmoid(linear)
                target = 1.0 if (safe_hit is not None and int(number) == safe_hit and safe_status == "win") else 0.0
                error = target - prediction
                weights["bias"] = _clamp(
                    float(weights.get("bias", 0.0)) + (learning_rate * error),
                    -AI_SHADOW_PROFILE_WEIGHT_LIMIT,
                    AI_SHADOW_PROFILE_WEIGHT_LIMIT,
                )
                for feature_name in AI_SHADOW_FEATURE_NAMES:
                    current = float(weights.get(feature_name, 0.0))
                    updated = current + (learning_rate * error * float(features.get(feature_name, 0.0)))
                    weights[feature_name] = _clamp(
                        updated,
                        -AI_SHADOW_PROFILE_WEIGHT_LIMIT,
                        AI_SHADOW_PROFILE_WEIGHT_LIMIT,
                    )

            profile["roulette_id"] = safe_roulette
            profile["weights"] = dict(weights)
            profile["signals"] = signals + 1
            profile["wins"] = int(profile.get("wins") or 0) + (1 if safe_status == "win" else 0)
            profile["losses"] = int(profile.get("losses") or 0) + (1 if safe_status == "loss" else 0)
            recent = list(profile.get("recent_outcomes") or [])
            recent.insert(0, {"status": safe_status, "hit_number": safe_hit, "signal_id": signal_id})
            profile["recent_outcomes"] = recent[:50]
            profile["updated_at"] = datetime.now(timezone.utc).isoformat()
            profiles[safe_roulette] = profile
            self._save(payload)

            log_entry = {
                "roulette_id": safe_roulette,
                "signal_id": signal_id,
                "status": safe_status,
                "hit_number": safe_hit,
                "attempts": int(attempts),
                "max_attempts": int(max_attempts),
                "confidence_score": int(confidence_score),
                "matched_episodes": int(matched_episodes),
                "avg_similarity": round(float(avg_similarity or 0.0), 6),
                "learning_rate": round(float(learning_rate), 6),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            with self._feedback_log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
            return copy.deepcopy(profile)


_PROFILE_STORE = AIShadowProfileStore()


def get_ai_shadow_profile_store() -> AIShadowProfileStore:
    return _PROFILE_STORE


def _profile_snapshot(profile: Mapping[str, Any]) -> Dict[str, Any]:
    weights = {str(name): round(float(value), 6) for name, value in dict(profile.get("weights") or {}).items()}
    ranked_weights = sorted(
        [{"feature": name, "weight": float(value)} for name, value in weights.items() if name != "bias"],
        key=lambda item: -abs(float(item["weight"])),
    )
    signals = int(profile.get("signals") or 0)
    wins = int(profile.get("wins") or 0)
    losses = int(profile.get("losses") or 0)
    return {
        "roulette_id": profile.get("roulette_id"),
        "signals": signals,
        "wins": wins,
        "losses": losses,
        "hit_rate": round((wins / signals), 4) if signals > 0 else 0.0,
        "weights": weights,
        "top_weights": ranked_weights[:8],
        "recent_outcomes": list(profile.get("recent_outcomes") or [])[:10],
        "updated_at": profile.get("updated_at"),
    }


def _last_seen_gap(history_values: Sequence[int], candidate: int) -> int:
    for offset, value in enumerate(reversed(history_values), start=1):
        if int(value) == int(candidate):
            return offset
    return AI_SHADOW_SLEEP_CAP + 1


def _terminal_bias_score(state_numbers: Sequence[int], candidate: int) -> float:
    if not state_numbers:
        return 0.0
    same_terminal = sum(1 for number in state_numbers if int(number) % 10 == int(candidate) % 10)
    return same_terminal / max(1, len(state_numbers))


def _build_candidate_features(
    *,
    history_values: Sequence[int],
    current_state: Mapping[str, Any],
    decoder_top_candidates: Sequence[Mapping[str, Any]],
    transition_snapshot: Mapping[str, Any],
    pending_snapshot: Mapping[str, Any],
) -> Dict[int, Dict[str, float]]:
    last_number = int(current_state.get("numbers", [0])[-1]) if current_state.get("numbers") else 0
    wheel_neighbors = set(get_wheel_neighbors_5_window(last_number, window=5))
    hotspot = dict(current_state.get("hotspot") or {})
    hotspot_center = hotspot.get("center")
    hotspot_numbers = {int(n) for n in hotspot.get("numbers") or []}

    decoder_score_raw: Dict[int, float] = {}
    decoder_rank_raw: Dict[int, float] = {}
    decoder_pool: List[int] = []
    for index, candidate in enumerate(decoder_top_candidates):
        try:
            number = int(candidate.get("number"))
        except (TypeError, ValueError):
            continue
        decoder_pool.append(number)
        decoder_score_raw[number] = float(candidate.get("final_score", 0.0) or 0.0)
        decoder_rank_raw[number] = 1.0 / (1.0 + index)

    transition_raw: Dict[int, float] = {}
    for entry in transition_snapshot.get("top_transitions") or []:
        try:
            transition_raw[int(entry.get("number"))] = float(entry.get("rate", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue

    pending_details = dict(pending_snapshot.get("candidate_details") or {})
    pending_raw: Dict[int, float] = {}
    candidate_pool = list(decoder_pool)
    for number_str, detail in pending_details.items():
        try:
            number = int(number_str)
        except (TypeError, ValueError):
            continue
        pending_raw[number] = float(detail.get("local_score", 0.0) or 0.0)
        if number not in candidate_pool:
            candidate_pool.append(number)

    for number in list(transition_raw.keys()):
        if number not in candidate_pool:
            candidate_pool.append(number)
    for number in wheel_neighbors:
        if number not in candidate_pool:
            candidate_pool.append(number)

    decoder_score = _normalize_float_map(decoder_score_raw)
    decoder_rank = _normalize_float_map(decoder_rank_raw)
    transition_rate = _normalize_float_map(transition_raw)
    pending_pressure = _normalize_float_map(pending_raw)

    recent_window = list(history_values[-AI_SHADOW_RECENT_WINDOW:])
    recent_counts = {candidate: recent_window.count(candidate) / max(1, len(recent_window)) for candidate in candidate_pool}

    feature_map: Dict[int, Dict[str, float]] = {}
    for number in candidate_pool:
        gap = _last_seen_gap(history_values, number)
        sleep_score = min(gap, AI_SHADOW_SLEEP_CAP) / AI_SHADOW_SLEEP_CAP
        freshness = 0.0 if number in history_values[-4:] else 1.0
        if hotspot_center is not None:
            proximity = 1.0 / (1.0 + _circular_distance(NUM2IDX[int(number)], NUM2IDX[int(hotspot_center)]))
        else:
            proximity = 0.0
        hotspot_bonus = 1.0 if number in hotspot_numbers else proximity
        feature_map[int(number)] = {
            "decoder_score": round(float(decoder_score.get(number, 0.0)), 6),
            "decoder_rank": round(float(decoder_rank.get(number, 0.0)), 6),
            "transition_rate": round(float(transition_rate.get(number, 0.0)), 6),
            "pending_pressure": round(float(pending_pressure.get(number, 0.0)), 6),
            "wheel_neighbor": 1.0 if number in wheel_neighbors else 0.0,
            "hotspot_proximity": round(float(hotspot_bonus), 6),
            "recent_frequency": round(float(recent_counts.get(number, 0.0)), 6),
            "sleep_score": round(float(sleep_score), 6),
            "freshness": round(float(freshness), 6),
            "terminal_bias": round(float(_terminal_bias_score(current_state.get("numbers") or [], number)), 6),
        }
    return feature_map


def _score_candidates(
    feature_map: Mapping[int, Mapping[str, float]],
    profile: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    weights = {**AI_SHADOW_DEFAULT_WEIGHTS, **dict(profile.get("weights") or {})}
    scored: List[Dict[str, Any]] = []
    for number, features in feature_map.items():
        linear = float(weights.get("bias", 0.0))
        contributions: Dict[str, float] = {}
        for feature_name in AI_SHADOW_FEATURE_NAMES:
            contribution = float(weights.get(feature_name, 0.0)) * float(features.get(feature_name, 0.0))
            contributions[feature_name] = round(float(contribution), 6)
            linear += contribution
        probability = _sigmoid(linear)
        scored.append(
            {
                "number": int(number),
                "linear_score": round(float(linear), 6),
                "probability": round(float(probability), 6),
                "final_score": round(float(probability), 6),
                "features": {name: round(float(value), 6) for name, value in dict(features).items()},
                "feature_contributions": contributions,
            }
        )
    scored.sort(key=lambda item: (-float(item["final_score"]), int(item["number"])))
    return scored


def _build_signal_candidate(
    *,
    scored_candidates: Sequence[Mapping[str, Any]],
    decoder_result: Mapping[str, Any],
    profile: Mapping[str, Any],
    top_k: int,
    min_confidence: int,
    min_matched_episodes: int,
) -> Dict[str, Any]:
    summary = decoder_result.get("summary") or {}
    suggestion = decoder_result.get("suggestion") or {}
    matched_episodes = int(summary.get("matched_episodes") or 0)
    safe_top_k = max(1, int(top_k))
    selected = [int(item["number"]) for item in scored_candidates[:safe_top_k]]
    top_probs = [float(item.get("probability", 0.0) or 0.0) for item in scored_candidates[: max(1, min(5, safe_top_k))]]
    avg_probability = sum(top_probs) / max(1, len(top_probs))
    concentration = (
        sum(float(item.get("final_score", 0.0) or 0.0) for item in scored_candidates[: min(5, len(scored_candidates))])
        / max(1e-9, sum(float(item.get("final_score", 0.0) or 0.0) for item in scored_candidates[: min(12, len(scored_candidates))]))
    ) if scored_candidates else 0.0
    baseline_overlap = len(set(selected) & set(suggestion.get("primary_numbers") or [])) / max(1, min(len(selected), 4))
    profile_support = min(1.0, int(profile.get("signals") or 0) / 40.0)
    confidence_score = round(
        100.0
        * (
            0.34 * avg_probability
            + 0.24 * concentration
            + 0.22 * min(1.0, matched_episodes / max(1, min_matched_episodes * 2))
            + 0.12 * baseline_overlap
            + 0.08 * profile_support
        )
    )
    reasons: List[str] = []
    if not bool(suggestion.get("available")):
        reasons.append("Decoder baseline indisponível.")
    if not selected:
        reasons.append("Nenhum candidato ranqueado pela IA.")
    if matched_episodes < min_matched_episodes:
        reasons.append(f"Episódios parecidos {matched_episodes} abaixo do mínimo {min_matched_episodes}.")
    if confidence_score < min_confidence:
        reasons.append(f"Confiança {confidence_score} abaixo do mínimo {min_confidence}.")
    emit = not reasons
    return {
        "emit": emit,
        "reason": "Sinal apto para shadow monitor." if emit else " ".join(reasons),
        "numbers": selected,
        "confidence_score": confidence_score,
        "confidence_label": decoder_lab._label_confidence(confidence_score),
        "matched_episodes": matched_episodes,
        "future_horizon": int(summary.get("future_horizon") or 0),
        "avg_probability": round(avg_probability, 6),
        "baseline_overlap": round(baseline_overlap, 6),
        "number_count_used": len(selected),
    }


def build_ai_shadow_analysis(
    rows: Sequence[Mapping[str, Any]],
    *,
    roulette_id: str,
    state_numbers: Sequence[int] | None = None,
    state_window: int = AI_SHADOW_DEFAULT_STATE_WINDOW,
    future_horizon: int = AI_SHADOW_DEFAULT_FUTURE_HORIZON,
    ignore_last_occurrence: bool = True,
    validation_ratio: float = AI_SHADOW_DEFAULT_VALIDATION_RATIO,
    min_support: int = AI_SHADOW_DEFAULT_MIN_SUPPORT,
    decoder_top_k: int = AI_SHADOW_DEFAULT_DECODER_TOP_K,
    top_k: int = AI_SHADOW_DEFAULT_TOP_K,
    episode_limit: int = AI_SHADOW_DEFAULT_EPISODE_LIMIT,
    similarity_threshold: float = AI_SHADOW_DEFAULT_SIMILARITY_THRESHOLD,
    min_confidence: int = AI_SHADOW_DEFAULT_MIN_CONFIDENCE,
    min_matched_episodes: int = AI_SHADOW_DEFAULT_MIN_MATCHED_EPISODES,
) -> Dict[str, Any]:
    normalized_rows = _normalize_rows(rows)
    decoder_result = decoder_lab.build_decoder_lab_analysis(
        normalized_rows,
        roulette_id=roulette_id,
        state_numbers=state_numbers,
        state_window=state_window,
        future_horizon=future_horizon,
        ignore_last_occurrence=ignore_last_occurrence,
        validation_ratio=validation_ratio,
        min_support=min_support,
        top_k=max(decoder_top_k, top_k),
        episode_limit=episode_limit,
        similarity_threshold=similarity_threshold,
    )
    profile = get_ai_shadow_profile_store().get_profile(roulette_id)

    if not normalized_rows:
        return {
            "available": False,
            "summary": {
                "roulette_id": roulette_id,
                "history_size": 0,
                "matched_episodes": 0,
                "future_horizon": future_horizon,
                "shadow_top_k": top_k,
            },
            "current_state": decoder_result.get("current_state") or {},
            "decoder": {
                "summary": decoder_result.get("summary") or {},
                "suggestion": decoder_result.get("suggestion") or {},
            },
            "profile": _profile_snapshot(profile),
            "shadow_candidates": [],
            "shadow_signal_candidate": {
                "emit": False,
                "reason": "Sem histórico disponível para a IA shadow.",
                "numbers": [],
                "confidence_score": 0,
                "confidence_label": "Muito baixa",
                "matched_episodes": 0,
                "future_horizon": future_horizon,
                "avg_probability": 0.0,
                "baseline_overlap": 0.0,
                "number_count_used": 0,
            },
        }

    history_values = [int(row["value"]) for row in normalized_rows]
    current_state = decoder_result.get("current_state") or {}
    transition_snapshot = decoder_result.get("transition_snapshot") or {}
    decoder_top_candidates = list(decoder_result.get("top_candidates") or [])[: max(top_k, decoder_top_k)]
    pending_snapshot = build_wheel_neighbors_5_pending_candidate_scores(
        history=list(reversed(history_values)),
        horizon_used=future_horizon,
        latest_base_number=(current_state.get("numbers") or [None])[-1],
        selection_size=max(top_k, 18),
    )
    feature_map = _build_candidate_features(
        history_values=history_values,
        current_state=current_state,
        decoder_top_candidates=decoder_top_candidates,
        transition_snapshot=transition_snapshot,
        pending_snapshot=pending_snapshot,
    )
    scored_candidates = _score_candidates(feature_map, profile)
    signal_candidate = _build_signal_candidate(
        scored_candidates=scored_candidates,
        decoder_result=decoder_result,
        profile=profile,
        top_k=top_k,
        min_confidence=min_confidence,
        min_matched_episodes=min_matched_episodes,
    )
    signal_feature_map = {
        str(item["number"]): copy.deepcopy(item["features"])
        for item in scored_candidates[: max(1, int(top_k))]
    }

    return {
        "available": bool(scored_candidates),
        "summary": {
            "roulette_id": roulette_id,
            "history_size": len(history_values),
            "matched_episodes": int((decoder_result.get("summary") or {}).get("matched_episodes") or 0),
            "future_horizon": future_horizon,
            "shadow_top_k": int(top_k),
            "decoder_top_k": int(decoder_top_k),
        },
        "current_state": current_state,
        "decoder": {
            "summary": decoder_result.get("summary") or {},
            "suggestion": decoder_result.get("suggestion") or {},
            "top_candidates": decoder_top_candidates,
        },
        "profile": _profile_snapshot(profile),
        "shadow_candidates": scored_candidates[: max(12, top_k)],
        "shadow_signal_candidate": {
            **signal_candidate,
            "feature_map": signal_feature_map,
        },
        "pending_snapshot": {
            "pending_bases": list((pending_snapshot.get("pending_state") or {}).get("pending_bases") or []),
            "candidate_ranking": list(pending_snapshot.get("candidate_ranking") or [])[:12],
        },
    }


def apply_ai_shadow_feedback(
    *,
    roulette_id: str,
    signal_id: str,
    feature_map: Mapping[str, Mapping[str, float]],
    candidate_numbers: Sequence[int],
    status: str,
    hit_number: int | None = None,
    confidence_score: int = 0,
    matched_episodes: int = 0,
    avg_similarity: float = 0.0,
    attempts: int = 0,
    max_attempts: int = 0,
) -> Dict[str, Any]:
    profile = get_ai_shadow_profile_store().apply_feedback(
        roulette_id=roulette_id,
        signal_id=signal_id,
        feature_map=feature_map,
        candidate_numbers=candidate_numbers,
        hit_number=hit_number,
        status=status,
        confidence_score=confidence_score,
        matched_episodes=matched_episodes,
        avg_similarity=avg_similarity,
        attempts=attempts,
        max_attempts=max_attempts,
    )
    return _profile_snapshot(profile)


async def load_ai_shadow_rows(
    *,
    roulette_id: str,
    days_back: int = AI_SHADOW_DEFAULT_DAYS_BACK,
    max_records: int = AI_SHADOW_DEFAULT_MAX_RECORDS,
) -> List[Dict[str, Any]]:
    query: Dict[str, Any] = {"roulette_id": roulette_id}
    if days_back > 0:
        query["timestamp"] = {"$gte": datetime.utcnow() - timedelta(days=days_back)}

    cursor = history_coll.find(query, {"_id": 0, "value": 1, "timestamp": 1}).sort("timestamp", -1)
    if max_records > 0:
        cursor = cursor.limit(max_records)

    rows = await cursor.to_list(length=max_records if max_records > 0 else None)
    rows.reverse()
    return rows


__all__ = [
    "AI_SHADOW_DEFAULT_TOP_K",
    "AI_SHADOW_DEFAULT_MIN_CONFIDENCE",
    "AI_SHADOW_DEFAULT_MIN_MATCHED_EPISODES",
    "AI_SHADOW_FEATURE_NAMES",
    "apply_ai_shadow_feedback",
    "build_ai_shadow_analysis",
    "get_ai_shadow_profile_store",
    "load_ai_shadow_rows",
]

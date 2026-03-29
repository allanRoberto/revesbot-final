from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping

from api.patterns.engine import pattern_engine
from api.patterns.final_suggestion import (
    build_final_suggestion,
    build_base_suggestion,
    build_focus_context,
    build_runtime_overrides,
    compute_confidence,
    normalize_weights,
)
from api.services.final_suggestion_signal_policy import final_suggestion_signal_policy


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


class PatternTrainingService:
    """Executa replay local para auditar padroes e sugerir pesos."""

    def __init__(self) -> None:
        self._definition_weights_cache: Dict[str, Dict[str, Any]] = {}

    def _load_definition_meta(self) -> Dict[str, Dict[str, Any]]:
        if self._definition_weights_cache:
            return dict(self._definition_weights_cache)

        base = getattr(pattern_engine, "_patterns_dir", None)
        patterns_dir = Path(base) if base else (Path(__file__).resolve().parent.parent / "patterns" / "definitions")
        out: Dict[str, Dict[str, Any]] = {}
        for path in sorted(patterns_dir.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            pattern_id = str(raw.get("id", "")).strip()
            if not pattern_id:
                continue
            out[pattern_id] = {
                "pattern_id": pattern_id,
                "pattern_name": str(raw.get("name", pattern_id)),
                "weight": float(raw.get("weight", 1.0) or 1.0),
                "kind": str(raw.get("kind", "positive")).lower(),
            }
        self._definition_weights_cache = dict(out)
        return out

    @staticmethod
    def _canonical_pattern_id(raw_pattern_id: str, known_pattern_ids: List[str]) -> str:
        raw = str(raw_pattern_id or "").strip()
        if not raw:
            return ""
        if raw in known_pattern_ids:
            return raw
        matches = [pid for pid in known_pattern_ids if raw.startswith(f"{pid}_")]
        if not matches:
            return raw
        matches.sort(key=len, reverse=True)
        return matches[0]

    @staticmethod
    def _parse_optimized_suggestion_sorted(result: Mapping[str, Any]) -> List[int]:
        out: List[int] = []
        for raw in result.get("suggestion", []) or []:
            try:
                number = int(raw)
            except (TypeError, ValueError):
                continue
            if 0 <= number <= 36 and number not in out:
                out.append(number)
        return out

    @staticmethod
    def _build_ranked_optimized_list(number_details: Any, fallback: List[int]) -> List[int]:
        if not isinstance(number_details, list):
            return list(fallback)

        ranked: List[tuple[float, int]] = []
        seen: set[int] = set()
        for item in number_details:
            if not isinstance(item, dict):
                continue
            try:
                number = int(item.get("number"))
            except (TypeError, ValueError):
                continue
            if not (0 <= number <= 36) or number in seen:
                continue
            seen.add(number)
            ranked.append((float(item.get("net_score", 0.0) or 0.0), number))

        ranked.sort(key=lambda pair: (-pair[0], pair[1]))
        ordered = [number for _, number in ranked]
        for number in fallback:
            if number not in ordered:
                ordered.append(number)
        return ordered

    @staticmethod
    def _find_hit(history: List[int], suggestion: List[int], from_index: int, max_attempts: int) -> Dict[str, Any]:
        if not suggestion:
            return {"hit": False, "hit_number": None, "hit_step": None}
        suggestion_set = {int(n) for n in suggestion if 0 <= int(n) <= 36}
        max_steps = min(max(0, int(from_index)), max(1, int(max_attempts)))
        for step in range(1, max_steps + 1):
            look_idx = from_index - step
            if look_idx < 0:
                break
            value = int(history[look_idx])
            if value in suggestion_set:
                return {"hit": True, "hit_number": value, "hit_step": step}
        return {"hit": False, "hit_number": None, "hit_step": None}

    @staticmethod
    def _sample_gate(sample_size: int, min_sample: int, full_sample: int) -> float:
        if sample_size <= min_sample:
            return 0.0
        if full_sample <= min_sample:
            return 1.0
        return _clamp((sample_size - min_sample) / (full_sample - min_sample), 0.0, 1.0)

    @staticmethod
    def _recent_miss_streak(recent_outcomes: List[bool], window: int) -> int:
        streak = 0
        for outcome in recent_outcomes[: max(1, int(window))]:
            if outcome:
                break
            streak += 1
        return streak

    def run_training(
        self,
        *,
        roulette_id: str,
        history: List[int],
        max_attempts: int = 4,
        optimized_max_numbers: int = 18,
        use_adaptive_weights: bool = False,
        min_sample: int = 20,
        full_sample: int = 120,
        prior_strength: float = 24.0,
        weight_floor: float = 0.75,
        weight_ceil: float = 1.30,
        lift_alpha: float = 0.85,
        recent_window: int = 30,
        recent_decay_start: int = 2,
        recent_decay_per_miss: float = 0.05,
        recent_decay_cap: float = 0.25,
        runtime_overrides: Dict[str, Dict[str, Any]] | None = None,
        base_weight: float = 0.5,
        optimized_weight: float = 0.5,
        block_bets_enabled: bool = False,
        inversion_enabled: bool = False,
        inversion_context_window: int = 15,
        inversion_penalty_factor: float = 0.3,
        siege_window: int = 6,
        siege_min_occurrences: int = 3,
        siege_min_streak: int = 2,
        siege_veto_relief: float = 0.4,
        policy_observation_window: int = 2,
        policy_pressure_window: int = 3,
        policy_min_block_touches: int = 1,
        policy_min_near_touches: int = 2,
        policy_confirm_window: int = 2,
        policy_switch_window: int = 3,
        policy_switch_min_score_delta: float = 6.0,
        policy_switch_min_confidence_delta: int = 4,
        policy_switch_min_hold_spins: int = 1,
        progress_callback: Callable[[Dict[str, Any]], None] | None = None,
    ) -> Dict[str, Any]:
        normalized_history = [int(n) for n in history if 0 <= int(n) <= 36]
        if len(normalized_history) <= max(2, int(max_attempts)):
            return {
                "available": False,
                "roulette_id": roulette_id,
                "message": "Historico insuficiente para treino.",
                "summary": {
                    "history_size": len(normalized_history),
                    "total_cases": 0,
                    "available_cases": 0,
                    "overall_hit_rate": 0.0,
                    "attributed_hit_rate": 0.0,
                },
                "patterns": [],
                "weights": {},
                "effective_weights": {},
                "signal_policies": {"available": False, "behavior": {}, "policies": {}, "opportunities": []},
            }

        definition_meta = self._load_definition_meta()
        known_positive_pattern_ids = sorted(
            [pid for pid, meta in definition_meta.items() if meta.get("kind") == "positive"]
        )
        pattern_rows: Dict[str, Dict[str, Any]] = {}
        total_cases = 0
        available_cases = 0
        hit_cases = 0
        total_attributed_hits = 0.0
        signal_policy_cases: List[Dict[str, Any]] = []

        merged_runtime_overrides = dict(runtime_overrides or {})
        prepared_runtime_overrides = build_runtime_overrides(
            runtime_overrides=merged_runtime_overrides,
            siege_window=max(2, int(siege_window)),
            siege_min_occurrences=max(1, int(siege_min_occurrences)),
            siege_min_streak=max(1, int(siege_min_streak)),
        )
        final_base_weight, final_optimized_weight = normalize_weights(base_weight, optimized_weight)
        total_iterations = max(0, len(normalized_history) - max(1, int(max_attempts)))
        progress_every = 10

        if progress_callback:
            progress_callback(
                {
                    "stage": "running",
                    "processed": 0,
                    "total": total_iterations,
                    "progress": 0.0,
                    "available_cases": 0,
                    "hit_cases": 0,
                }
            )

        for idx in range(max(1, int(max_attempts)), len(normalized_history)):
            total_cases += 1
            focus_number = int(normalized_history[idx])
            focus_context = build_focus_context(
                history=normalized_history,
                focus_number=focus_number,
                from_index=idx,
            )
            bucket = focus_context["bucket"]
            pulled_counts = focus_context["pulled_counts"]
            pulled_total = len(focus_context["pulled"])
            base_list_ranked = build_base_suggestion(
                bucket=bucket,
                pulled_counts=pulled_counts,
                total_pulled=pulled_total,
                source_arr=normalized_history,
                from_index=idx,
                siege_window=max(2, int(siege_window)),
                siege_min_occurrences=max(1, int(siege_min_occurrences)),
                siege_min_streak=max(1, int(siege_min_streak)),
                siege_veto_relief=float(siege_veto_relief),
                preserve_ranking=True,
            )
            engine_result = pattern_engine.evaluate(
                history=normalized_history,
                base_suggestion=sorted(base_list_ranked),
                focus_number=focus_number,
                from_index=idx,
                max_numbers=max(1, min(37, int(optimized_max_numbers))),
                runtime_overrides=prepared_runtime_overrides,
                use_adaptive_weights=bool(use_adaptive_weights),
            )
            if not bool(engine_result.get("available", False)):
                if progress_callback and (total_cases % progress_every == 0 or total_cases == total_iterations):
                    progress_callback(
                        {
                            "stage": "running",
                            "processed": total_cases,
                            "total": total_iterations,
                            "progress": round(total_cases / max(1, total_iterations), 4),
                            "available_cases": available_cases,
                            "hit_cases": hit_cases,
                        }
                    )
                continue

            available_cases += 1
            contributions = engine_result.get("contributions", [])
            if not isinstance(contributions, list):
                contributions = []

            active_pattern_ids: List[str] = []
            seen_active: set[str] = set()
            for contrib in contributions:
                if not isinstance(contrib, dict):
                    continue
                base_pid = self._canonical_pattern_id(contrib.get("pattern_id", ""), known_positive_pattern_ids)
                if not base_pid or base_pid in seen_active:
                    continue
                seen_active.add(base_pid)
                active_pattern_ids.append(base_pid)
                meta = definition_meta.get(base_pid, {})
                row = pattern_rows.setdefault(
                    base_pid,
                    {
                        "pattern_id": base_pid,
                        "pattern_name": str(meta.get("pattern_name", base_pid)),
                        "base_weight": float(meta.get("weight", 1.0) or 1.0),
                        "sample_size": 0,
                        "support_hits": 0,
                        "attributed_hits": 0.0,
                        "hit_at_1": 0.0,
                        "hit_at_2": 0.0,
                        "hit_at_4": 0.0,
                        "hit_at_10": 0.0,
                        "recent_outcomes": [],
                    },
                )
                row["sample_size"] += 1

            if not active_pattern_ids:
                continue

            hit_info = self._find_hit(
                history=normalized_history,
                suggestion=[int(n) for n in engine_result.get("suggestion", []) if 0 <= int(n) <= 36],
                from_index=idx,
                max_attempts=max_attempts,
            )
            hit_number = hit_info["hit_number"]
            hit_step = hit_info["hit_step"]
            hit = bool(hit_info["hit"])
            if hit:
                hit_cases += 1

            support_weights: Dict[str, float] = {}
            if hit and hit_number is not None:
                for item in engine_result.get("number_details", []) or []:
                    if not isinstance(item, dict):
                        continue
                    try:
                        detail_number = int(item.get("number"))
                    except (TypeError, ValueError):
                        continue
                    if detail_number != int(hit_number):
                        continue
                    for positive in item.get("positive_patterns", []) or []:
                        if not isinstance(positive, dict):
                            continue
                        base_pid = self._canonical_pattern_id(positive.get("pattern_id", ""), known_positive_pattern_ids)
                        if not base_pid:
                            continue
                        support_weights[base_pid] = support_weights.get(base_pid, 0.0) + float(
                            positive.get("weight", 0.0) or 0.0
                        )
                    break

            support_total = sum(weight for weight in support_weights.values() if weight > 0)
            case_attributed = 0.0
            for base_pid in active_pattern_ids:
                row = pattern_rows[base_pid]
                credit = 0.0
                if support_total > 0 and base_pid in support_weights:
                    credit = max(0.0, float(support_weights[base_pid]) / support_total)
                    row["support_hits"] += 1
                    row["attributed_hits"] += credit
                    case_attributed += credit
                    if hit_step is not None and int(hit_step) <= 1:
                        row["hit_at_1"] += credit
                    if hit_step is not None and int(hit_step) <= 2:
                        row["hit_at_2"] += credit
                    if hit_step is not None and int(hit_step) <= 4:
                        row["hit_at_4"] += credit
                    if hit_step is not None and int(hit_step) <= 10:
                        row["hit_at_10"] += credit
                row["recent_outcomes"].append(credit > 0.0)
            total_attributed_hits += min(1.0, case_attributed)

            base_confidence = compute_confidence(bucket, pulled_total)
            base_confidence_score = int(base_confidence.get("score", 0) or 0)
            opt_list_sorted = self._parse_optimized_suggestion_sorted(engine_result)
            opt_ranked = self._build_ranked_optimized_list(
                engine_result.get("number_details", []),
                opt_list_sorted,
            )
            final_result = build_final_suggestion(
                base_list=base_list_ranked,
                optimized_list=opt_ranked,
                optimized_confidence=int(engine_result.get("confidence", {}).get("score", 0) or 0),
                optimized_confidence_effective=int(
                    engine_result.get("confidence_breakdown", {}).get("calibrated_confidence_v2", 0)
                    or engine_result.get("confidence", {}).get("score", 0)
                    or 0
                ),
                number_details=engine_result.get("number_details", []) if isinstance(engine_result.get("number_details", []), list) else [],
                base_confidence_score=base_confidence_score,
                max_size=max(1, min(37, int(optimized_max_numbers))),
                history_arr=normalized_history,
                from_index=idx,
                pulled_counts=pulled_counts,
                base_weight=final_base_weight,
                optimized_weight=final_optimized_weight,
                block_bets_enabled=bool(block_bets_enabled),
                inversion_enabled=bool(inversion_enabled),
                inversion_context_window=max(1, int(inversion_context_window)),
                inversion_penalty_factor=float(inversion_penalty_factor),
            )
            final_suggestion = [int(n) for n in final_result.get("list", []) if 0 <= int(n) <= 36]
            future_numbers = [
                int(normalized_history[idx - step])
                for step in range(1, min(int(max_attempts), idx) + 1)
            ]
            extended_window = min(
                idx,
                int(max_attempts) + max(int(policy_switch_window), int(policy_confirm_window), 2),
            )
            extended_future_numbers = [
                int(normalized_history[idx - step])
                for step in range(1, extended_window + 1)
            ]
            final_hit_info = self._find_hit(
                history=normalized_history,
                suggestion=final_suggestion,
                from_index=idx,
                max_attempts=max_attempts,
            )
            confidence_score = int(final_result.get("confidence", {}).get("score", 0) or 0)
            suggestion_size = len(final_suggestion)
            policy_score = confidence_score - (suggestion_size * 1.5)
            if bool(final_result.get("blockCompaction", {}).get("changed")):
                policy_score += 3.0
            signal_policy_cases.append(
                {
                    "focus_number": focus_number,
                    "from_index": idx,
                    "confidence_score": confidence_score,
                    "suggestion": final_suggestion,
                    "suggestion_size": suggestion_size,
                    "policy_score": round(float(policy_score), 4),
                    "exact_hit_step": final_hit_info.get("hit_step"),
                    "future_numbers": future_numbers,
                    "extended_future_numbers": extended_future_numbers,
                    "block_bets_enabled": bool(block_bets_enabled),
                    "block_compaction_applied": bool(final_result.get("blockCompaction", {}).get("changed")),
                }
            )

            if progress_callback and (total_cases % progress_every == 0 or total_cases == total_iterations):
                progress_callback(
                    {
                        "stage": "running",
                        "processed": total_cases,
                        "total": total_iterations,
                        "progress": round(total_cases / max(1, total_iterations), 4),
                        "available_cases": available_cases,
                        "hit_cases": hit_cases,
                    }
                )

        if available_cases <= 0:
            return {
                "available": False,
                "roulette_id": roulette_id,
                "message": "Nenhum caso disponivel para treino.",
                "summary": {
                    "history_size": len(normalized_history),
                    "total_cases": total_cases,
                    "available_cases": 0,
                    "overall_hit_rate": 0.0,
                    "attributed_hit_rate": 0.0,
                },
                "patterns": [],
                "weights": {},
                "effective_weights": {},
                "signal_policies": {"available": False, "behavior": {}, "policies": {}, "opportunities": []},
            }

        baseline_attr_rate = _clamp(total_attributed_hits / max(1, available_cases), 1e-4, 1.0)
        patterns: List[Dict[str, Any]] = []
        weights: Dict[str, float] = {}
        effective_weights: Dict[str, float] = {}

        for pattern_id, row in pattern_rows.items():
            sample_size = max(1, int(row["sample_size"]))
            attributed_hits = float(row["attributed_hits"])
            attributed_hit_rate = attributed_hits / sample_size
            support_hit_rate = float(row["support_hits"]) / sample_size
            sample_gate = self._sample_gate(
                sample_size=sample_size,
                min_sample=max(1, int(min_sample)),
                full_sample=max(int(min_sample) + 1, int(full_sample)),
            )
            posterior_rate = (attributed_hits + (baseline_attr_rate * float(prior_strength))) / (
                sample_size + float(prior_strength)
            )
            lift = posterior_rate / baseline_attr_rate
            miss_streak = self._recent_miss_streak(
                recent_outcomes=list(row["recent_outcomes"]),
                window=max(1, int(recent_window)),
            )
            if miss_streak <= int(recent_decay_start):
                recent_decay = 0.0
            else:
                extra = miss_streak - int(recent_decay_start)
                recent_decay = _clamp(
                    extra * float(recent_decay_per_miss),
                    0.0,
                    float(recent_decay_cap),
                )
            target_weight = 1.0 + ((lift - 1.0) * float(lift_alpha) * sample_gate)
            target_weight *= (1.0 - recent_decay)
            recommended_multiplier = _clamp(target_weight, float(weight_floor), float(weight_ceil))
            effective_weight = float(row["base_weight"]) * recommended_multiplier

            item = {
                "pattern_id": pattern_id,
                "pattern_name": row["pattern_name"],
                "base_weight": round(float(row["base_weight"]), 6),
                "sample_size": sample_size,
                "coverage": round(sample_size / available_cases, 6),
                "support_hits": int(row["support_hits"]),
                "attributed_hits": round(attributed_hits, 6),
                "support_hit_rate": round(support_hit_rate, 6),
                "attributed_hit_rate": round(attributed_hit_rate, 6),
                "hit_at_1": round(float(row["hit_at_1"]) / sample_size, 6),
                "hit_at_2": round(float(row["hit_at_2"]) / sample_size, 6),
                "hit_at_4": round(float(row["hit_at_4"]) / sample_size, 6),
                "hit_at_10": round(float(row["hit_at_10"]) / sample_size, 6),
                "posterior_rate": round(float(posterior_rate), 6),
                "lift": round(float(lift), 6),
                "sample_gate": round(float(sample_gate), 6),
                "recent_miss_streak": int(miss_streak),
                "recent_decay": round(float(recent_decay), 6),
                "recommended_multiplier": round(float(recommended_multiplier), 6),
                "effective_weight": round(float(effective_weight), 6),
            }
            patterns.append(item)
            weights[pattern_id] = item["recommended_multiplier"]
            effective_weights[pattern_id] = item["effective_weight"]

        patterns.sort(
            key=lambda item: (
                -float(item.get("attributed_hit_rate", 0.0)),
                -int(item.get("sample_size", 0)),
                item.get("pattern_id", ""),
            )
        )
        signal_policies = final_suggestion_signal_policy.analyze_cases(
            cases=signal_policy_cases,
            max_attempts=max_attempts,
            observation_window=max(1, int(policy_observation_window)),
            pressure_window=max(1, int(policy_pressure_window)),
            min_block_touches=max(1, int(policy_min_block_touches)),
            min_near_touches=max(1, int(policy_min_near_touches)),
            confirm_window=max(1, int(policy_confirm_window)),
            switch_window=max(1, int(policy_switch_window)),
            switch_min_score_delta=float(policy_switch_min_score_delta),
            switch_min_confidence_delta=max(0, int(policy_switch_min_confidence_delta)),
            switch_min_hold_spins=max(1, int(policy_switch_min_hold_spins)),
        )
        summary = {
            "history_size": len(normalized_history),
            "total_cases": int(total_cases),
            "available_cases": int(available_cases),
            "overall_hit_cases": int(hit_cases),
            "overall_hit_rate": round(hit_cases / max(1, available_cases), 6),
            "attributed_hit_rate": round(total_attributed_hits / max(1, available_cases), 6),
            "baseline_attributed_rate": round(float(baseline_attr_rate), 6),
            "signal_policy_behavior": signal_policies.get("behavior", {}),
        }
        config = {
            "roulette_id": roulette_id,
            "max_attempts": int(max_attempts),
            "optimized_max_numbers": int(optimized_max_numbers),
            "use_adaptive_weights": bool(use_adaptive_weights),
            "base_weight": float(final_base_weight),
            "optimized_weight": float(final_optimized_weight),
            "block_bets_enabled": bool(block_bets_enabled),
            "inversion_enabled": bool(inversion_enabled),
            "inversion_context_window": int(inversion_context_window),
            "inversion_penalty_factor": float(inversion_penalty_factor),
            "siege_window": int(siege_window),
            "siege_min_occurrences": int(siege_min_occurrences),
            "siege_min_streak": int(siege_min_streak),
            "siege_veto_relief": float(siege_veto_relief),
            "min_sample": int(min_sample),
            "full_sample": int(full_sample),
            "prior_strength": float(prior_strength),
            "weight_floor": float(weight_floor),
            "weight_ceil": float(weight_ceil),
            "lift_alpha": float(lift_alpha),
            "recent_window": int(recent_window),
            "recent_decay_start": int(recent_decay_start),
            "recent_decay_per_miss": float(recent_decay_per_miss),
            "recent_decay_cap": float(recent_decay_cap),
            "policy_observation_window": int(policy_observation_window),
            "policy_pressure_window": int(policy_pressure_window),
            "policy_min_block_touches": int(policy_min_block_touches),
            "policy_min_near_touches": int(policy_min_near_touches),
            "policy_confirm_window": int(policy_confirm_window),
            "policy_switch_window": int(policy_switch_window),
            "policy_switch_min_score_delta": float(policy_switch_min_score_delta),
            "policy_switch_min_confidence_delta": int(policy_switch_min_confidence_delta),
            "policy_switch_min_hold_spins": int(policy_switch_min_hold_spins),
        }
        return {
            "available": True,
            "roulette_id": roulette_id,
            "summary": summary,
            "config": config,
            "patterns": patterns,
            "weights": weights,
            "effective_weights": effective_weights,
            "signal_policies": signal_policies,
        }


pattern_training_service = PatternTrainingService()

from __future__ import annotations

from typing import Any, Callable, Dict, List

from api.patterns.engine import PatternDefinition, pattern_engine
from api.patterns.final_suggestion import (
    build_base_suggestion,
    build_focus_context,
    build_runtime_overrides,
)


WAIT_EVALUATOR_IDS = {
    "color_neighbor_alternation_missing_entry",
    "exact_alternation_delayed_entry",
    "exact_repeat_delayed_entry",
    "neighbor_repeat_delayed_entry",
    "repeat_trend_next_projection_delayed_entry",
    "terminal_alternation_middle_entry",
    "terminal_repeat_next_sum_wait_neighbors",
    "terminal_repeat_sum_delayed_entry",
    "terminal_repeat_wait_spins_neighbors",
    "trend_alternation_middle_projection_entry",
}

HIT_SCORE_BY_STEP = {
    1: 0.3,
    2: 0.2,
    3: 0.1,
}
MISS_SCORE = -0.3
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_TIMELINE_WINDOW = 80


class PatternScoreTrainingService:
    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))

    def _load_immediate_positive_patterns(self) -> List[PatternDefinition]:
        return [
            definition
            for definition in pattern_engine._load_patterns()
            if definition.kind == "positive" and definition.evaluator not in WAIT_EVALUATOR_IDS
        ]

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
    def _normalize_numbers(numbers: Any) -> List[int]:
        out: List[int] = []
        seen: set[int] = set()
        for raw in numbers or []:
            try:
                value = int(raw)
            except (TypeError, ValueError):
                continue
            if not (0 <= value <= 36) or value in seen:
                continue
            seen.add(value)
            out.append(value)
        out.sort()
        return out

    def _extract_active_patterns(
        self,
        *,
        contributions: Any,
        definitions_by_id: Dict[str, PatternDefinition],
        known_pattern_ids: List[str],
    ) -> List[Dict[str, Any]]:
        aggregated: Dict[str, Dict[str, Any]] = {}
        if not isinstance(contributions, list):
            return []

        for item in contributions:
            if not isinstance(item, dict):
                continue
            base_pattern_id = self._canonical_pattern_id(item.get("pattern_id", ""), known_pattern_ids)
            definition = definitions_by_id.get(base_pattern_id)
            if definition is None:
                continue
            numbers = self._normalize_numbers(item.get("numbers", []))
            if not numbers:
                continue
            row = aggregated.setdefault(
                base_pattern_id,
                {
                    "pattern_id": base_pattern_id,
                    "pattern_name": definition.name,
                    "numbers": [],
                    "_seen_numbers": set(),
                },
            )
            seen_numbers: set[int] = row["_seen_numbers"]
            for number in numbers:
                if number in seen_numbers:
                    continue
                seen_numbers.add(number)
                row["numbers"].append(number)

        active_patterns: List[Dict[str, Any]] = []
        for item in aggregated.values():
            numbers = sorted(int(n) for n in item.get("numbers", []))
            if not numbers:
                continue
            active_patterns.append(
                {
                    "pattern_id": item["pattern_id"],
                    "pattern_name": item["pattern_name"],
                    "numbers": numbers,
                }
            )
        active_patterns.sort(key=lambda row: row["pattern_name"])
        return active_patterns

    @staticmethod
    def _compute_expected_score(suggestion_size: int, max_attempts: int) -> float:
        safe_size = max(0, min(37, int(suggestion_size)))
        safe_attempts = max(1, min(3, int(max_attempts)))
        if safe_size <= 0:
            return float(MISS_SCORE)

        p = float(safe_size) / 37.0
        expected_score = 0.0
        miss_prefix = 1.0
        for step in range(1, safe_attempts + 1):
            hit_weight = float(HIT_SCORE_BY_STEP.get(step, 0.0))
            hit_prob = miss_prefix * p
            expected_score += hit_weight * hit_prob
            miss_prefix *= (1.0 - p)
        expected_score += float(MISS_SCORE) * miss_prefix
        return expected_score

    @staticmethod
    def _resolve_outcome(history: List[int], suggestion: List[int], from_index: int, max_attempts: int) -> Dict[str, Any]:
        suggestion_set = {int(number) for number in suggestion if 0 <= int(number) <= 36}
        future_numbers: List[int] = []
        hit_step: int | None = None
        hit_number: int | None = None

        for step in range(1, max(1, int(max_attempts)) + 1):
            look_idx = from_index - step
            if look_idx < 0:
                break
            value = int(history[look_idx])
            future_numbers.append(value)
            if hit_step is None and value in suggestion_set:
                hit_step = step
                hit_number = value

        if hit_step is not None:
            score_delta = float(HIT_SCORE_BY_STEP.get(int(hit_step), 0.0))
            result_label = f"HIT T{int(hit_step)}"
        else:
            score_delta = float(MISS_SCORE)
            result_label = "MISS"

        expected_score = PatternScoreTrainingService._compute_expected_score(
            suggestion_size=len(suggestion_set),
            max_attempts=max_attempts,
        )
        adjusted_score_delta = float(score_delta) - float(expected_score)

        return {
            "hit": hit_step is not None,
            "hit_step": hit_step,
            "hit_number": hit_number,
            "future_numbers": future_numbers,
            "raw_score_delta": score_delta,
            "expected_score": expected_score,
            "adjusted_score_delta": adjusted_score_delta,
            "result_label": result_label,
        }

    @staticmethod
    def _build_pattern_row(definition: PatternDefinition) -> Dict[str, Any]:
        return {
            "pattern_id": definition.id,
            "pattern_name": definition.name,
            "activations": 0,
            "hits_t1": 0,
            "hits_t2": 0,
            "hits_t3": 0,
            "misses": 0,
            "raw_score": 0.0,
            "adjusted_score": 0.0,
            "expected_score_sum": 0.0,
            "suggestion_size_sum": 0,
            "last_suggestion": [],
            "last_result": "-",
            "last_raw_score_delta": 0.0,
            "last_adjusted_score_delta": 0.0,
            "last_expected_score": 0.0,
            "last_focus_number": None,
        }

    @staticmethod
    def _serialize_rows(pattern_rows: Dict[str, Dict[str, Any]], definitions: List[PatternDefinition]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for definition in definitions:
            row = dict(pattern_rows.get(definition.id) or {})
            activations = int(row.get("activations", 0) or 0)
            hits_t1 = int(row.get("hits_t1", 0) or 0)
            hits_t2 = int(row.get("hits_t2", 0) or 0)
            hits_t3 = int(row.get("hits_t3", 0) or 0)
            misses = int(row.get("misses", 0) or 0)
            total_hits = hits_t1 + hits_t2 + hits_t3
            raw_score = float(row.get("raw_score", 0.0) or 0.0)
            adjusted_score = float(row.get("adjusted_score", 0.0) or 0.0)
            suggestion_size_sum = int(row.get("suggestion_size_sum", 0) or 0)
            rows.append(
                {
                    "pattern_id": definition.id,
                    "pattern_name": definition.name,
                    "base_weight": round(float(definition.weight), 6),
                    "activations": activations,
                    "hits_t1": hits_t1,
                    "hits_t2": hits_t2,
                    "hits_t3": hits_t3,
                    "total_hits": total_hits,
                    "misses": misses,
                    "raw_score": round(raw_score, 4),
                    "adjusted_score": round(adjusted_score, 4),
                    "avg_raw_score": round((raw_score / activations), 4) if activations > 0 else 0.0,
                    "avg_adjusted_score": round((adjusted_score / activations), 4) if activations > 0 else 0.0,
                    "avg_suggestion_size": round((suggestion_size_sum / activations), 2) if activations > 0 else 0.0,
                    "hit_rate": round((total_hits / activations), 4) if activations > 0 else 0.0,
                    "last_suggestion": list(row.get("last_suggestion", []) or []),
                    "last_result": str(row.get("last_result", "-") or "-"),
                    "last_raw_score_delta": round(float(row.get("last_raw_score_delta", 0.0) or 0.0), 4),
                    "last_adjusted_score_delta": round(float(row.get("last_adjusted_score_delta", 0.0) or 0.0), 4),
                    "last_expected_score": round(float(row.get("last_expected_score", 0.0) or 0.0), 4),
                    "last_focus_number": row.get("last_focus_number"),
                }
            )
        rows.sort(key=lambda item: (-float(item["adjusted_score"]), -int(item["activations"]), item["pattern_name"]))
        return rows

    def build_profile_material(
        self,
        *,
        result: Dict[str, Any],
        multiplier_alpha: float = 3.0,
        weight_floor: float = 0.7,
        weight_ceil: float = 1.5,
        activation_full_sample: int = 30,
    ) -> Dict[str, Any]:
        definitions_by_id = {
            definition.id: definition
            for definition in self._load_immediate_positive_patterns()
        }
        source_patterns = result.get("patterns", []) if isinstance(result, dict) else []
        if not isinstance(source_patterns, list):
            source_patterns = []

        patterns: List[Dict[str, Any]] = []
        weights: Dict[str, float] = {}
        effective_weights: Dict[str, float] = {}
        safe_floor = float(weight_floor)
        safe_ceil = max(safe_floor, float(weight_ceil))
        safe_alpha = float(multiplier_alpha)
        safe_full_sample = max(1, int(activation_full_sample))

        for item in source_patterns:
            if not isinstance(item, dict):
                continue
            pattern_id = str(item.get("pattern_id", "")).strip()
            definition = definitions_by_id.get(pattern_id)
            if definition is None:
                continue
            activations = max(0, int(item.get("activations", 0) or 0))
            avg_adjusted_score = float(item.get("avg_adjusted_score", 0.0) or 0.0)
            sample_gate = min(1.0, activations / float(safe_full_sample))
            recommended_multiplier = self._clamp(
                1.0 + (avg_adjusted_score * safe_alpha * sample_gate),
                safe_floor,
                safe_ceil,
            )
            effective_weight = float(definition.weight) * recommended_multiplier
            row = dict(item)
            row.update(
                {
                    "base_weight": round(float(definition.weight), 6),
                    "sample_gate": round(sample_gate, 6),
                    "recommended_multiplier": round(recommended_multiplier, 6),
                    "effective_weight": round(effective_weight, 6),
                }
            )
            patterns.append(row)
            weights[pattern_id] = row["recommended_multiplier"]
            effective_weights[pattern_id] = row["effective_weight"]

        patterns.sort(
            key=lambda item: (
                -float(item.get("adjusted_score", 0.0) or 0.0),
                -int(item.get("activations", 0) or 0),
                str(item.get("pattern_id", "")),
            )
        )
        return {
            "patterns": patterns,
            "weights": weights,
            "effective_weights": effective_weights,
            "config": {
                "training_mode": "score-training",
                "score_mode": "size_adjusted",
                "multiplier_alpha": safe_alpha,
                "weight_floor": safe_floor,
                "weight_ceil": safe_ceil,
                "activation_full_sample": safe_full_sample,
            },
        }

    @staticmethod
    def _build_summary(
        *,
        pattern_rows: Dict[str, Dict[str, Any]],
        history_size: int,
        processed_spins: int,
        total_spins: int,
        patterns_count: int,
    ) -> Dict[str, Any]:
        total_activations = 0
        total_hits = 0
        total_misses = 0
        total_raw_score = 0.0
        total_adjusted_score = 0.0

        for row in pattern_rows.values():
            total_activations += int(row.get("activations", 0) or 0)
            total_hits += (
                int(row.get("hits_t1", 0) or 0)
                + int(row.get("hits_t2", 0) or 0)
                + int(row.get("hits_t3", 0) or 0)
            )
            total_misses += int(row.get("misses", 0) or 0)
            total_raw_score += float(row.get("raw_score", 0.0) or 0.0)
            total_adjusted_score += float(row.get("adjusted_score", 0.0) or 0.0)

        return {
            "history_size": int(history_size),
            "processed_spins": int(processed_spins),
            "total_spins": int(total_spins),
            "patterns_count": int(patterns_count),
            "total_activations": int(total_activations),
            "total_hits": int(total_hits),
            "total_misses": int(total_misses),
            "activation_hit_rate": round((total_hits / total_activations), 4) if total_activations > 0 else 0.0,
            "total_raw_score": round(total_raw_score, 4),
            "total_adjusted_score": round(total_adjusted_score, 4),
        }

    def run_training(
        self,
        *,
        roulette_id: str,
        history: List[int],
        history_limit: int,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        timeline_window: int = DEFAULT_TIMELINE_WINDOW,
        progress_callback: Callable[[Dict[str, Any]], None] | None = None,
    ) -> Dict[str, Any]:
        safe_max_attempts = max(1, min(3, int(max_attempts)))
        normalized_history = [int(number) for number in history if 0 <= int(number) <= 36]
        immediate_patterns = self._load_immediate_positive_patterns()
        definitions_by_id = {definition.id: definition for definition in immediate_patterns}
        known_pattern_ids = list(definitions_by_id.keys())
        pattern_rows = {
            definition.id: self._build_pattern_row(definition)
            for definition in immediate_patterns
        }

        total_spins = max(0, len(normalized_history) - safe_max_attempts)
        if total_spins <= 0 or not immediate_patterns:
            return {
                "available": False,
                "roulette_id": roulette_id,
                "config": {
                    "history_limit": int(history_limit),
                    "max_attempts": safe_max_attempts,
                    "patterns_count": len(immediate_patterns),
                },
                "summary": self._build_summary(
                    pattern_rows=pattern_rows,
                    history_size=len(normalized_history),
                    processed_spins=0,
                    total_spins=total_spins,
                    patterns_count=len(immediate_patterns),
                ),
                "patterns": self._serialize_rows(pattern_rows, immediate_patterns),
                "weights": {definition.id: 0.0 for definition in immediate_patterns},
                "timeline": [],
                "current_number": None,
                "current_activations": [],
                "message": "Historico insuficiente para treino simples.",
            }

        runtime_overrides = build_runtime_overrides(
            runtime_overrides={},
            siege_window=5,
            siege_min_occurrences=3,
            siege_min_streak=2,
        )
        processed_timeline: List[int] = []
        current_number: int | None = None
        current_activations: List[Dict[str, Any]] = []

        if progress_callback:
            progress_callback(
                {
                    "stage": "running",
                    "processed": 0,
                    "total": total_spins,
                    "progress": 0.0,
                    "current_number": None,
                    "timeline": [],
                    "current_activations": [],
                    "summary": self._build_summary(
                        pattern_rows=pattern_rows,
                        history_size=len(normalized_history),
                        processed_spins=0,
                        total_spins=total_spins,
                        patterns_count=len(immediate_patterns),
                    ),
                    "patterns": self._serialize_rows(pattern_rows, immediate_patterns),
                }
            )

        for processed_spins, from_index in enumerate(
            range(len(normalized_history) - 1, safe_max_attempts - 1, -1),
            start=1,
        ):
            focus_number = int(normalized_history[from_index])
            current_number = focus_number
            processed_timeline.append(focus_number)
            focus_context = build_focus_context(
                history=normalized_history,
                focus_number=focus_number,
                from_index=from_index,
            )
            base_list_ranked = build_base_suggestion(
                bucket=focus_context["bucket"],
                pulled_counts=focus_context["pulled_counts"],
                total_pulled=len(focus_context["pulled"]),
                source_arr=normalized_history,
                from_index=from_index,
                siege_window=5,
                siege_min_occurrences=3,
                siege_min_streak=2,
                siege_veto_relief=0.4,
                preserve_ranking=True,
            )
            engine_result = pattern_engine.evaluate(
                history=normalized_history,
                base_suggestion=sorted(base_list_ranked),
                focus_number=focus_number,
                from_index=from_index,
                max_numbers=37,
                use_adaptive_weights=False,
                runtime_overrides=runtime_overrides,
                use_fallback=False,
            )
            active_patterns = self._extract_active_patterns(
                contributions=engine_result.get("contributions", []),
                definitions_by_id=definitions_by_id,
                known_pattern_ids=known_pattern_ids,
            )

            current_activations = []
            for item in active_patterns:
                outcome = self._resolve_outcome(
                    history=normalized_history,
                    suggestion=item["numbers"],
                    from_index=from_index,
                    max_attempts=safe_max_attempts,
                )
                row = pattern_rows[item["pattern_id"]]
                row["activations"] += 1
                row["suggestion_size_sum"] += len(item["numbers"])
                row["last_suggestion"] = list(item["numbers"])
                row["last_result"] = outcome["result_label"]
                row["last_raw_score_delta"] = float(outcome["raw_score_delta"])
                row["last_adjusted_score_delta"] = float(outcome["adjusted_score_delta"])
                row["last_expected_score"] = float(outcome["expected_score"])
                row["last_focus_number"] = focus_number
                row["raw_score"] += float(outcome["raw_score_delta"])
                row["adjusted_score"] += float(outcome["adjusted_score_delta"])
                row["expected_score_sum"] += float(outcome["expected_score"])
                if outcome["hit_step"] == 1:
                    row["hits_t1"] += 1
                elif outcome["hit_step"] == 2:
                    row["hits_t2"] += 1
                elif outcome["hit_step"] == 3:
                    row["hits_t3"] += 1
                else:
                    row["misses"] += 1
                current_activations.append(
                    {
                        "pattern_id": item["pattern_id"],
                        "pattern_name": item["pattern_name"],
                        "numbers": list(item["numbers"]),
                        "future_numbers": list(outcome["future_numbers"]),
                        "hit": bool(outcome["hit"]),
                        "hit_step": outcome["hit_step"],
                        "hit_number": outcome["hit_number"],
                        "raw_score_delta": round(float(outcome["raw_score_delta"]), 4),
                        "expected_score": round(float(outcome["expected_score"]), 4),
                        "adjusted_score_delta": round(float(outcome["adjusted_score_delta"]), 4),
                        "suggestion_size": len(item["numbers"]),
                        "result_label": outcome["result_label"],
                    }
                )
            current_activations.sort(
                key=lambda item: (-float(item["adjusted_score_delta"]), item["pattern_name"])
            )

            if progress_callback:
                progress_callback(
                    {
                        "stage": "running",
                        "processed": processed_spins,
                        "total": total_spins,
                        "progress": round(processed_spins / max(1, total_spins), 4),
                        "current_number": current_number,
                        "current_from_index": from_index,
                        "timeline": list(processed_timeline[-max(10, int(timeline_window)):]),
                        "current_activations": current_activations,
                        "summary": self._build_summary(
                            pattern_rows=pattern_rows,
                            history_size=len(normalized_history),
                            processed_spins=processed_spins,
                            total_spins=total_spins,
                            patterns_count=len(immediate_patterns),
                        ),
                        "patterns": self._serialize_rows(pattern_rows, immediate_patterns),
                    }
                )

        final_patterns = self._serialize_rows(pattern_rows, immediate_patterns)
        final_summary = self._build_summary(
            pattern_rows=pattern_rows,
            history_size=len(normalized_history),
            processed_spins=total_spins,
            total_spins=total_spins,
            patterns_count=len(immediate_patterns),
        )
        return {
            "available": True,
            "roulette_id": roulette_id,
            "config": {
                "history_limit": int(history_limit),
                "history_size": len(normalized_history),
                "max_attempts": safe_max_attempts,
                "patterns_count": len(immediate_patterns),
            },
            "summary": final_summary,
            "patterns": final_patterns,
            "weights": {
                row["pattern_id"]: float(row["adjusted_score"])
                for row in final_patterns
            },
            "timeline": list(processed_timeline[-max(10, int(timeline_window)):]),
            "current_number": current_number,
            "current_activations": current_activations,
            "message": "Treino simples concluido.",
        }


pattern_score_training_service = PatternScoreTrainingService()

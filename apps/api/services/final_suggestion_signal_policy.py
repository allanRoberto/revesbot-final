from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Sequence

from api.patterns.final_suggestion import ROULETTE_EUROPEAN_NUMBERS


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


class FinalSuggestionSignalPolicyService:
    """Audita atraso de hit e vantagem potencial de troca entre sinais consecutivos."""

    def __init__(self) -> None:
        self._wheel_index = {number: index for index, number in enumerate(ROULETTE_EUROPEAN_NUMBERS)}

    def _wheel_distance(self, a: int, b: int) -> int:
        idx_a = self._wheel_index.get(int(a))
        idx_b = self._wheel_index.get(int(b))
        if idx_a is None or idx_b is None:
            return 99
        raw = abs(idx_a - idx_b)
        return min(raw, len(ROULETTE_EUROPEAN_NUMBERS) - raw)

    def _is_near_hit(self, value: int, suggestion: Sequence[int]) -> bool:
        for number in suggestion:
            if self._wheel_distance(int(value), int(number)) <= 1:
                return True
        return False

    def _min_distance_to_suggestion(self, value: int, suggestion: Sequence[int]) -> int:
        if not suggestion:
            return 99
        return min(self._wheel_distance(int(value), int(number)) for number in suggestion)

    def _avg_distance_to_suggestion(self, values: Sequence[int], suggestion: Sequence[int]) -> float:
        if not values or not suggestion:
            return 99.0
        distances = [self._min_distance_to_suggestion(int(value), suggestion) for value in values]
        return float(sum(distances) / len(distances))

    def _is_recent_cluster(self, values: Sequence[int], max_span: int = 3) -> bool:
        numbers = [int(value) for value in values]
        if len(numbers) < 2:
            return False
        max_distance = 0
        for idx, left in enumerate(numbers):
            for right in numbers[idx + 1:]:
                max_distance = max(max_distance, self._wheel_distance(left, right))
        return max_distance <= int(max_span)

    @staticmethod
    def _count_recent_hits(values: Sequence[int], suggestion: Sequence[int]) -> int:
        suggestion_set = {int(number) for number in suggestion}
        return sum(1 for value in values if int(value) in suggestion_set)

    @staticmethod
    def _repeat_streak(values: Sequence[int]) -> int:
        numbers = [int(value) for value in values]
        if not numbers:
            return 0
        streak = 1
        current = 1
        for index in range(1, len(numbers)):
            if numbers[index] == numbers[index - 1]:
                current += 1
                streak = max(streak, current)
            else:
                current = 1
        return streak

    @staticmethod
    def _first_hit_step(future_numbers: Sequence[int], suggestion_set: set[int]) -> int | None:
        for step, value in enumerate(future_numbers, start=1):
            if int(value) in suggestion_set:
                return step
        return None

    @staticmethod
    def _first_hit_after_step(
        future_numbers: Sequence[int],
        suggestion_set: set[int],
        min_step_exclusive: int,
    ) -> int | None:
        for step, value in enumerate(future_numbers, start=1):
            if step <= int(min_step_exclusive):
                continue
            if int(value) in suggestion_set:
                return step
        return None

    def _first_near_hit_step(self, future_numbers: Sequence[int], suggestion: Sequence[int], suggestion_set: set[int]) -> int | None:
        for step, value in enumerate(future_numbers, start=1):
            number = int(value)
            if number in suggestion_set:
                continue
            if self._is_near_hit(number, suggestion):
                return step
        return None

    @staticmethod
    def _avg(values: Sequence[float]) -> float:
        if not values:
            return 0.0
        return float(sum(values) / len(values))

    def analyze_cases(
        self,
        *,
        cases: Sequence[Mapping[str, Any]],
        max_attempts: int,
        observation_window: int = 2,
        pressure_window: int = 3,
        min_block_touches: int = 1,
        min_near_touches: int = 2,
        confirm_window: int = 2,
        switch_window: int = 3,
        switch_min_score_delta: float = 6.0,
        switch_min_confidence_delta: int = 4,
        switch_min_hold_spins: int = 1,
        max_examples: int = 12,
    ) -> Dict[str, Any]:
        safe_attempts = max(1, int(max_attempts))
        safe_observation = max(1, min(safe_attempts, int(observation_window)))
        safe_pressure = max(safe_observation, min(safe_attempts, int(pressure_window)))
        safe_confirm = max(1, int(confirm_window))
        safe_switch_window = max(1, int(switch_window))
        safe_hold_spins = max(1, int(switch_min_hold_spins))
        ordered_cases = sorted(
            [dict(item) for item in cases if isinstance(item, Mapping)],
            key=lambda item: -int(item.get("from_index", 0)),
        )

        if not ordered_cases:
            return {
                "available": False,
                "behavior": {},
                "policies": {},
                "opportunities": [],
            }

        hold_hits = 0
        hold_delays: List[float] = []
        hold_block_delays: List[float] = []
        late_hits = 0
        block_before_exact = 0
        block_gap_sum = 0.0
        repeat_after_hit = 0

        wait_armed = 0
        wait_hits = 0
        wait_arm_steps: List[float] = []
        wait_delays: List[float] = []
        wait_missed_fast_hits = 0

        switch_recommended = 0
        switch_hits = 0
        switch_delays: List[float] = []
        switch_improved = 0
        switch_saved_steps: List[float] = []
        switch_worsened = 0
        switch_examples: List[Dict[str, Any]] = []

        for index, case in enumerate(ordered_cases):
            suggestion = [int(n) for n in (case.get("suggestion") or []) if 0 <= int(n) <= 36]
            suggestion_set = set(suggestion)
            future_numbers = [int(n) for n in (case.get("future_numbers") or []) if 0 <= int(n) <= 36][:safe_attempts]
            extended_future = [int(n) for n in (case.get("extended_future_numbers") or []) if 0 <= int(n) <= 36]
            if not suggestion_set or not future_numbers:
                continue

            confidence_score = int(case.get("confidence_score", 0) or 0)
            suggestion_size = max(1, int(case.get("suggestion_size", len(suggestion)) or len(suggestion)))
            policy_score = float(case.get("policy_score", confidence_score - (suggestion_size * 1.5)))

            exact_hit_step = case.get("exact_hit_step")
            if exact_hit_step is None:
                exact_hit_step = self._first_hit_step(future_numbers, suggestion_set)
            block_hit_step = case.get("block_hit_step")
            if block_hit_step is None:
                block_hit_step = self._first_hit_step(future_numbers[:safe_pressure], suggestion_set)
            near_hit_step = case.get("near_hit_step")
            if near_hit_step is None:
                near_hit_step = self._first_near_hit_step(future_numbers[:safe_pressure], suggestion, suggestion_set)
            late_hit_step = case.get("late_exact_hit_step")
            if late_hit_step is None and extended_future:
                late_hit_step = self._first_hit_step(extended_future, suggestion_set)

            if exact_hit_step is not None and exact_hit_step <= safe_attempts:
                hold_hits += 1
                hold_delays.append(float(exact_hit_step))
                pressure_hit_step = min(
                    [step for step in (block_hit_step, near_hit_step) if step is not None],
                    default=None,
                )
                if pressure_hit_step is not None:
                    hold_block_delays.append(float(pressure_hit_step))
                    if pressure_hit_step < exact_hit_step:
                        block_before_exact += 1
                        block_gap_sum += float(exact_hit_step - pressure_hit_step)
                end = min(len(future_numbers), exact_hit_step + safe_confirm)
                if any(int(n) in suggestion_set for n in future_numbers[exact_hit_step:end]):
                    repeat_after_hit += 1
            elif late_hit_step is not None and late_hit_step > safe_attempts:
                late_hits += 1

            arm_step: int | None = None
            block_touches = 0
            near_touches = 0
            for step, value in enumerate(future_numbers[:safe_observation], start=1):
                number = int(value)
                if number in suggestion_set:
                    block_touches += 1
                elif self._is_near_hit(number, suggestion):
                    near_touches += 1
                if block_touches >= int(min_block_touches) or near_touches >= int(min_near_touches):
                    arm_step = step
                    break

            if arm_step is not None:
                wait_armed += 1
                wait_arm_steps.append(float(arm_step))
                if exact_hit_step is not None and exact_hit_step <= arm_step:
                    wait_missed_fast_hits += 1
                armed_hit_step = self._first_hit_after_step(future_numbers, suggestion_set, arm_step)
                if armed_hit_step is not None and armed_hit_step <= safe_attempts:
                    wait_hits += 1
                    wait_delays.append(float(armed_hit_step))

            hold_delay = float(exact_hit_step) if exact_hit_step is not None and exact_hit_step <= safe_attempts else math.inf
            switched_delay = hold_delay
            switched_to: Dict[str, Any] | None = None

            for offset in range(safe_hold_spins, safe_switch_window + 1):
                next_pos = index + offset
                if next_pos >= len(ordered_cases):
                    break
                if hold_delay < offset:
                    break
                candidate = ordered_cases[next_pos]
                candidate_suggestion = [int(n) for n in (candidate.get("suggestion") or []) if 0 <= int(n) <= 36]
                if not candidate_suggestion:
                    continue
                candidate_confidence = int(candidate.get("confidence_score", 0) or 0)
                candidate_size = max(1, int(candidate.get("suggestion_size", len(candidate_suggestion)) or len(candidate_suggestion)))
                candidate_score = float(candidate.get("policy_score", candidate_confidence - (candidate_size * 1.5)))
                better_score = candidate_score >= (policy_score + float(switch_min_score_delta))
                better_confidence = candidate_confidence >= (confidence_score + int(switch_min_confidence_delta))
                smaller_block = candidate_size <= max(1, suggestion_size - 2)
                if not (better_score or (better_confidence and smaller_block)):
                    continue

                candidate_hit = candidate.get("exact_hit_step")
                if candidate_hit is None:
                    candidate_hit = self._first_hit_step(
                        [int(n) for n in (candidate.get("future_numbers") or []) if 0 <= int(n) <= 36][:safe_attempts],
                        set(candidate_suggestion),
                    )
                candidate_abs_delay = math.inf
                if candidate_hit is not None:
                    candidate_abs_delay = float(offset + int(candidate_hit))
                switched_delay = candidate_abs_delay
                switched_to = {
                    "offset": int(offset),
                    "from_index": int(candidate.get("from_index", 0)),
                    "focus_number": int(candidate.get("focus_number", 0)),
                    "confidence_score": candidate_confidence,
                    "suggestion_size": candidate_size,
                    "policy_score": round(candidate_score, 4),
                    "absolute_delay": None if not math.isfinite(candidate_abs_delay) else int(candidate_abs_delay),
                }
                break

            effective_switch_delay = switched_delay if switched_to is not None else hold_delay
            if math.isfinite(effective_switch_delay) and effective_switch_delay <= safe_attempts:
                switch_hits += 1
                switch_delays.append(float(effective_switch_delay))

            if switched_to is not None:
                switch_recommended += 1
                if switched_delay < hold_delay:
                    switch_improved += 1
                    switch_saved_steps.append(float(hold_delay - switched_delay))
                    switch_examples.append(
                        {
                            "focus_number": int(case.get("focus_number", 0)),
                            "from_index": int(case.get("from_index", 0)),
                            "current_confidence": confidence_score,
                            "current_size": suggestion_size,
                            "current_delay": None if not math.isfinite(hold_delay) else int(hold_delay),
                            "switch_to": switched_to,
                            "saved_steps": None if not math.isfinite(hold_delay) else int(hold_delay - switched_delay),
                        }
                    )
                elif switched_delay > hold_delay and math.isfinite(switched_delay):
                    switch_worsened += 1

        analyzed = max(1, len(ordered_cases))
        block_before_exact_rate = block_before_exact / max(1, hold_hits)
        avg_block_gap = block_gap_sum / max(1, block_before_exact)
        switch_examples.sort(
            key=lambda item: (
                -int(item.get("saved_steps") or 0),
                -int(item.get("current_confidence") or 0),
                item.get("from_index", 0),
            )
        )

        return {
            "available": True,
            "behavior": {
                "cases": int(analyzed),
                "hold_hits": int(hold_hits),
                "late_hit_rate": round(late_hits / analyzed, 6),
                "block_before_exact_rate": round(block_before_exact_rate, 6),
                "avg_block_to_exact_gap": round(avg_block_gap, 6),
                "repeat_after_exact_rate": round(repeat_after_hit / max(1, hold_hits), 6),
            },
            "policies": {
                "hold": {
                    "label": "Segurar",
                    "hit_rate": round(hold_hits / analyzed, 6),
                    "avg_hit_delay": round(self._avg(hold_delays), 6),
                    "avg_block_delay": round(self._avg(hold_block_delays), 6),
                },
                "wait_for_pressure": {
                    "label": "Esperar Pressao",
                    "armed_rate": round(wait_armed / analyzed, 6),
                    "hit_rate": round(wait_hits / analyzed, 6),
                    "avg_arm_step": round(self._avg(wait_arm_steps), 6),
                    "avg_hit_delay": round(self._avg(wait_delays), 6),
                    "missed_fast_hit_rate": round(wait_missed_fast_hits / analyzed, 6),
                },
                "switch_if_better": {
                    "label": "Trocar se Melhor",
                    "switch_rate": round(switch_recommended / analyzed, 6),
                    "hit_rate": round(switch_hits / analyzed, 6),
                    "improved_rate": round(switch_improved / max(1, switch_recommended), 6),
                    "worsened_rate": round(switch_worsened / max(1, switch_recommended), 6),
                    "avg_hit_delay": round(self._avg(switch_delays), 6),
                    "avg_saved_steps": round(self._avg(switch_saved_steps), 6),
                },
            },
            "opportunities": switch_examples[: max(1, int(max_examples))],
        }

    def recommend_live_transition(
        self,
        *,
        active_signal: Mapping[str, Any] | None,
        candidate_signal: Mapping[str, Any] | None,
        history: Sequence[int] | None = None,
        focus_number: int | None = None,
        observation_window: int = 2,
        min_hold_spins: int = 1,
        switch_min_score_delta: float = 6.0,
        switch_min_confidence_delta: int = 4,
    ) -> Dict[str, Any]:
        candidate = dict(candidate_signal or {})
        active = dict(active_signal or {})

        candidate_list = [int(n) for n in (candidate.get("suggestion") or []) if 0 <= int(n) <= 36]
        candidate_confidence = int(candidate.get("confidence_score", 0) or 0)
        candidate_size = max(1, int(candidate.get("suggestion_size", len(candidate_list)) or len(candidate_list) or 1))
        candidate_score = float(candidate.get("policy_score", candidate_confidence - (candidate_size * 1.5)))
        candidate_block = bool(candidate.get("block_compaction_applied"))
        candidate_overlap = set(candidate_list)
        recent_history = [int(n) for n in (history or []) if 0 <= int(n) <= 36][: max(4, int(observation_window) + 2)]

        if candidate_block:
            candidate_score += 3.0

        if not active:
            action = "enter" if candidate_confidence > 0 and candidate_list else "wait"
            reason = "Nenhum sinal ativo." if action == "enter" else "Sem sugestão candidata."
            return {
                "action": action,
                "label": "Entrar Agora" if action == "enter" else "Esperar",
                "reason": reason,
                "candidate_score": round(candidate_score, 4),
                "active_score": 0.0,
                "score_delta": round(candidate_score, 4),
                "confidence_delta": candidate_confidence,
                "overlap_ratio": 0.0,
                "saved_steps_estimate": 0,
            }

        active_list = [int(n) for n in (active.get("suggestion") or []) if 0 <= int(n) <= 36]
        active_confidence = int(active.get("confidence_score", 0) or 0)
        active_size = max(1, int(active.get("suggestion_size", len(active_list)) or len(active_list) or 1))
        active_score = float(active.get("policy_score", active_confidence - (active_size * 1.5)))
        active_block = bool(active.get("block_compaction_applied"))
        attempts_used = max(0, int(active.get("attempts_used", 0) or 0))
        max_attempts = max(1, int(active.get("max_attempts", 1) or 1))
        active_overlap = set(active_list)

        if active_block:
            active_score += 3.0

        score_delta = candidate_score - active_score
        confidence_delta = candidate_confidence - active_confidence
        overlap_ratio = 0.0
        if active_overlap or candidate_overlap:
            overlap_ratio = len(active_overlap.intersection(candidate_overlap)) / max(1, len(active_overlap.union(candidate_overlap)))

        repeated_head = len(recent_history) >= 2 and recent_history[0] == recent_history[1]
        repeat_streak = self._repeat_streak(recent_history[:4])
        clustered_recent = self._is_recent_cluster(recent_history[:3], max_span=3)
        active_recent_distance = self._avg_distance_to_suggestion(recent_history[:3], active_list)
        candidate_recent_distance = self._avg_distance_to_suggestion(recent_history[:3], candidate_list)
        recent_active_hits = self._count_recent_hits(recent_history[1:5], active_list)
        recent_candidate_hits = self._count_recent_hits(recent_history[1:5], candidate_list)
        repeat_lock = repeat_streak >= 2 and active_recent_distance >= 2.5 and recent_active_hits == 0

        mesa_travada_fora_da_regiao = (
            (repeat_lock or clustered_recent)
            and active_recent_distance >= 3.0
            and recent_active_hits == 0
            and (candidate_recent_distance >= 3.0 or recent_candidate_hits == 0)
        )

        if repeat_lock or mesa_travada_fora_da_regiao:
            cluster_text = "repeticao imediata" if repeat_lock else "cluster curto na mesma regiao"
            focus_text = f" apos o {int(focus_number)}" if isinstance(focus_number, int) else ""
            return {
                "action": "wait",
                "label": "Esperar",
                "reason": f"Mesa travada em {cluster_text}{focus_text}, ainda longe da regiao sugerida.",
                "candidate_score": round(candidate_score, 4),
                "active_score": round(active_score, 4),
                "score_delta": round(score_delta, 4),
                "confidence_delta": int(confidence_delta),
                "overlap_ratio": round(overlap_ratio, 4),
                "saved_steps_estimate": 0,
                "recent_clustered": bool(clustered_recent),
                "repeated_head": bool(repeated_head),
                "repeat_lock": bool(repeat_lock),
                "repeat_streak": int(repeat_streak),
                "active_recent_distance": round(active_recent_distance, 4),
                "candidate_recent_distance": round(candidate_recent_distance, 4),
            }

        if attempts_used < max(1, int(min_hold_spins)):
            return {
                "action": "hold",
                "label": "Segurar",
                "reason": f"Sinal ainda dentro do minimo de {max(1, int(min_hold_spins))} giro(s) antes de trocar.",
                "candidate_score": round(candidate_score, 4),
                "active_score": round(active_score, 4),
                "score_delta": round(score_delta, 4),
                "confidence_delta": int(confidence_delta),
                "overlap_ratio": round(overlap_ratio, 4),
                "saved_steps_estimate": 0,
                "recent_clustered": bool(clustered_recent),
                "repeated_head": bool(repeated_head),
                "repeat_lock": bool(repeat_lock),
                "repeat_streak": int(repeat_streak),
                "active_recent_distance": round(active_recent_distance, 4),
                "candidate_recent_distance": round(candidate_recent_distance, 4),
            }

        better_score = score_delta >= float(switch_min_score_delta)
        better_confidence = confidence_delta >= int(switch_min_confidence_delta)
        smaller_block = candidate_size <= max(1, active_size - 2)
        low_overlap = overlap_ratio <= 0.45

        if better_score and low_overlap:
            saved_steps = max(1, min(max_attempts - attempts_used, int(round(score_delta / max(1.0, switch_min_score_delta)))))
            return {
                "action": "switch",
                "label": "Trocar",
                "reason": "Nova sugestao superou claramente o sinal atual em score efetivo.",
                "candidate_score": round(candidate_score, 4),
                "active_score": round(active_score, 4),
                "score_delta": round(score_delta, 4),
                "confidence_delta": int(confidence_delta),
                "overlap_ratio": round(overlap_ratio, 4),
                "saved_steps_estimate": int(saved_steps),
                "recent_clustered": bool(clustered_recent),
                "repeated_head": bool(repeated_head),
                "repeat_lock": bool(repeat_lock),
                "repeat_streak": int(repeat_streak),
                "active_recent_distance": round(active_recent_distance, 4),
                "candidate_recent_distance": round(candidate_recent_distance, 4),
            }

        if better_confidence and smaller_block and low_overlap:
            saved_steps = max(1, min(max_attempts - attempts_used, 1 + int(round(max(0, confidence_delta) / max(1, switch_min_confidence_delta)))))
            return {
                "action": "switch",
                "label": "Trocar",
                "reason": "Nova sugestao ficou mais concentrada e com confianca superior.",
                "candidate_score": round(candidate_score, 4),
                "active_score": round(active_score, 4),
                "score_delta": round(score_delta, 4),
                "confidence_delta": int(confidence_delta),
                "overlap_ratio": round(overlap_ratio, 4),
                "saved_steps_estimate": int(saved_steps),
                "recent_clustered": bool(clustered_recent),
                "repeated_head": bool(repeated_head),
                "repeat_lock": bool(repeat_lock),
                "repeat_streak": int(repeat_streak),
                "active_recent_distance": round(active_recent_distance, 4),
                "candidate_recent_distance": round(candidate_recent_distance, 4),
            }

        if attempts_used < max(1, int(observation_window)):
            return {
                "action": "wait",
                "label": "Esperar",
                "reason": "Sinal atual ainda em observacao; aguardando pressao suficiente para trocar.",
                "candidate_score": round(candidate_score, 4),
                "active_score": round(active_score, 4),
                "score_delta": round(score_delta, 4),
                "confidence_delta": int(confidence_delta),
                "overlap_ratio": round(overlap_ratio, 4),
                "saved_steps_estimate": 0,
                "recent_clustered": bool(clustered_recent),
                "repeated_head": bool(repeated_head),
                "repeat_lock": bool(repeat_lock),
                "repeat_streak": int(repeat_streak),
                "active_recent_distance": round(active_recent_distance, 4),
                "candidate_recent_distance": round(candidate_recent_distance, 4),
            }

        return {
            "action": "hold",
            "label": "Segurar",
            "reason": "Nova sugestao nao mostrou vantagem suficiente para abandonar a atual.",
            "candidate_score": round(candidate_score, 4),
            "active_score": round(active_score, 4),
            "score_delta": round(score_delta, 4),
            "confidence_delta": int(confidence_delta),
            "overlap_ratio": round(overlap_ratio, 4),
            "saved_steps_estimate": 0,
            "recent_clustered": bool(clustered_recent),
            "repeated_head": bool(repeated_head),
            "repeat_lock": bool(repeat_lock),
            "repeat_streak": int(repeat_streak),
            "active_recent_distance": round(active_recent_distance, 4),
            "candidate_recent_distance": round(candidate_recent_distance, 4),
        }


final_suggestion_signal_policy = FinalSuggestionSignalPolicyService()

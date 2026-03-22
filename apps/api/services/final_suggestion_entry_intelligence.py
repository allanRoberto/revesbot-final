from __future__ import annotations

from typing import Any, Dict, Mapping, Sequence

from api.patterns.final_suggestion import ROULETTE_EUROPEAN_NUMBERS


class FinalSuggestionEntryIntelligenceService:
    def __init__(self) -> None:
        self._wheel_index = {number: index for index, number in enumerate(ROULETTE_EUROPEAN_NUMBERS)}
        self._sector_count = 6
        self._sector_size = max(1, len(ROULETTE_EUROPEAN_NUMBERS) // self._sector_count)

    def _wheel_distance(self, a: int, b: int) -> int:
        idx_a = self._wheel_index.get(int(a))
        idx_b = self._wheel_index.get(int(b))
        if idx_a is None or idx_b is None:
            return 99
        raw = abs(idx_a - idx_b)
        return min(raw, len(ROULETTE_EUROPEAN_NUMBERS) - raw)

    def _sector_id(self, value: int) -> int:
        index = self._wheel_index.get(int(value))
        if index is None:
            return -1
        return index // self._sector_size

    def _nearest_distance(self, value: int, suggestion: Sequence[int]) -> int:
        if not suggestion:
            return 99
        return min(self._wheel_distance(int(value), int(number)) for number in suggestion)

    def _touch_recent_region(self, recent_numbers: Sequence[int], suggestion: Sequence[int]) -> Dict[str, int]:
        exact = 0
        near = 0
        close = 0
        for value in recent_numbers:
            distance = self._nearest_distance(int(value), suggestion)
            if distance == 0:
                exact += 1
            elif distance == 1:
                near += 1
            elif distance == 2:
                close += 1
        return {"exact": exact, "near": near, "close": close}

    def _recent_regions(self, recent_numbers: Sequence[int]) -> Dict[str, Any]:
        sectors = [self._sector_id(int(value)) for value in recent_numbers if self._sector_id(int(value)) >= 0]
        unique_ordered = []
        for sector in sectors:
            if sector not in unique_ordered:
                unique_ordered.append(sector)
        transitions = sum(1 for idx in range(1, len(sectors)) if sectors[idx] != sectors[idx - 1])
        alternating = 2 <= len(set(sectors)) <= 3 and transitions >= max(1, len(sectors) - 2)
        return {
            "sectors": sectors,
            "unique": unique_ordered[:3],
            "alternating": alternating,
            "transitions": transitions,
        }

    def _alignment_with_regions(self, suggestion: Sequence[int], regions: Sequence[int]) -> float:
        if not suggestion or not regions:
            return 0.0
        region_set = set(int(region) for region in regions)
        aligned = 0
        for number in suggestion:
            sector = self._sector_id(int(number))
            if sector in region_set:
                aligned += 1
                continue
            if any(abs(sector - region) == 1 for region in region_set):
                aligned += 0.5
        return float(aligned / max(1, len(suggestion)))

    def _relation_score(self, last_number: int | None, previous_number: int | None, suggestion: Sequence[int]) -> float:
        if not suggestion:
            return 0.0
        score = 0.0
        if isinstance(last_number, int):
            last_distance = self._nearest_distance(last_number, suggestion)
            if last_distance == 0:
                score += 30.0
            elif last_distance == 1:
                score += 20.0
            elif last_distance == 2:
                score += 8.0
            elif last_distance >= 4:
                score -= min(18.0, (last_distance - 3) * 4.5)
            if any(abs(int(last_number) - int(number)) == 1 for number in suggestion):
                score += 6.0
        if isinstance(previous_number, int):
            prev_distance = self._nearest_distance(previous_number, suggestion)
            if prev_distance == 0:
                score += 14.0
            elif prev_distance == 1:
                score += 10.0
            elif prev_distance == 2:
                score += 4.0
            if any(abs(int(previous_number) - int(number)) == 1 for number in suggestion):
                score += 4.0
        return score

    def _max_wait_spins(self, suggestion_size: int) -> int:
        return 3 if int(suggestion_size) > 12 else 6

    def _decay_penalty(self, wait_spins: int, max_wait: int) -> float:
        if max_wait <= 0:
            return 0.0
        ratio = min(1.5, max(0.0, float(wait_spins) / float(max_wait)))
        return ratio * 18.0

    def _build_signal_metrics(
        self,
        *,
        suggestion: Sequence[int],
        confidence_score: int,
        policy_score: float,
        block_compaction_applied: bool,
        history: Sequence[int],
        wait_spins: int,
    ) -> Dict[str, Any]:
        recent_five = [int(n) for n in history[:5] if 0 <= int(n) <= 36]
        recent_three = recent_five[:3]
        last_number = recent_five[0] if recent_five else None
        previous_number = recent_five[1] if len(recent_five) > 1 else None
        touch = self._touch_recent_region(recent_five, suggestion)
        recent_regions = self._recent_regions(recent_five[:6])
        alignment = self._alignment_with_regions(suggestion, recent_regions["unique"])
        last_distance = self._nearest_distance(last_number, suggestion) if isinstance(last_number, int) else 99
        max_wait = self._max_wait_spins(len(suggestion))
        decay_penalty = self._decay_penalty(wait_spins, max_wait)
        touch_score = (touch["exact"] * 16.0) + (touch["near"] * 9.0) + (touch["close"] * 4.0)
        alternation_score = (12.0 * alignment) if recent_regions["alternating"] else (4.0 * alignment)
        relation_score = self._relation_score(last_number, previous_number, suggestion)
        score = float(policy_score)
        score += (confidence_score * 0.18)
        score += touch_score
        score += alternation_score
        score += relation_score
        if block_compaction_applied:
            score += 4.0
        score -= decay_penalty
        return {
            "score": round(score, 4),
            "touch_exact": touch["exact"],
            "touch_near": touch["near"],
            "touch_close": touch["close"],
            "last_distance": int(last_distance),
            "recent_regions": recent_regions["unique"],
            "alternating_regions": bool(recent_regions["alternating"]),
            "region_alignment": round(alignment, 4),
            "relation_score": round(relation_score, 4),
            "wait_spins": int(wait_spins),
            "max_wait_allowed": int(max_wait),
            "decay_penalty": round(decay_penalty, 4),
        }

    def recommend(
        self,
        *,
        active_signal: Mapping[str, Any] | None,
        candidate_signal: Mapping[str, Any] | None,
        history: Sequence[int] | None = None,
    ) -> Dict[str, Any]:
        recent_history = [int(n) for n in (history or []) if 0 <= int(n) <= 36]
        candidate = dict(candidate_signal or {})
        candidate_list = [int(n) for n in (candidate.get("suggestion") or []) if 0 <= int(n) <= 36]
        candidate_confidence = int(candidate.get("confidence_score", 0) or 0)
        candidate_base_score = float(candidate.get("policy_score", candidate_confidence - (len(candidate_list) * 1.5)))
        candidate_metrics = self._build_signal_metrics(
            suggestion=candidate_list,
            confidence_score=candidate_confidence,
            policy_score=candidate_base_score,
            block_compaction_applied=bool(candidate.get("block_compaction_applied")),
            history=recent_history,
            wait_spins=0,
        )

        if not candidate_list:
            return {
                "action": "wait",
                "label": "Esperar",
                "reason": "Sem sugestão candidata válida.",
                "score_delta": 0.0,
                "confidence_delta": 0,
                "overlap_ratio": 0.0,
                "saved_steps_estimate": 0,
                **candidate_metrics,
            }

        if not active_signal:
            if candidate_metrics["touch_exact"] > 0 or candidate_metrics["touch_near"] > 0 or candidate_metrics["last_distance"] <= 1:
                return {
                    "action": "enter",
                    "label": "Entrar Agora",
                    "reason": "Região da sugestão já foi tocada recentemente e a mesa está alinhada.",
                    "score_delta": round(candidate_metrics["score"], 4),
                    "confidence_delta": int(candidate_confidence),
                    "overlap_ratio": 0.0,
                    "saved_steps_estimate": 0,
                    **candidate_metrics,
                }
            if candidate_metrics["alternating_regions"] and candidate_metrics["region_alignment"] >= 0.35:
                return {
                    "action": "enter",
                    "label": "Entrar Agora",
                    "reason": "Mesa alternando entre regiões compatíveis com a sugestão.",
                    "score_delta": round(candidate_metrics["score"], 4),
                    "confidence_delta": int(candidate_confidence),
                    "overlap_ratio": 0.0,
                    "saved_steps_estimate": 0,
                    **candidate_metrics,
                }
            return {
                "action": "wait",
                "label": "Esperar",
                "reason": "Mesa ainda não tocou a região da sugestão com força suficiente.",
                "score_delta": round(candidate_metrics["score"], 4),
                "confidence_delta": int(candidate_confidence),
                "overlap_ratio": 0.0,
                "saved_steps_estimate": 0,
                **candidate_metrics,
            }

        active = dict(active_signal)
        active_list = [int(n) for n in (active.get("suggestion") or []) if 0 <= int(n) <= 36]
        active_confidence = int(active.get("confidence_score", 0) or 0)
        active_base_score = float(active.get("policy_score", active_confidence - (len(active_list) * 1.5)))
        attempts_used = max(0, int(active.get("attempts_used", 0) or 0))
        max_attempts = max(1, int(active.get("max_attempts", 1) or 1))
        wait_spins = max(0, int(active.get("wait_spins", 0) or 0))
        active_metrics = self._build_signal_metrics(
            suggestion=active_list,
            confidence_score=active_confidence,
            policy_score=active_base_score,
            block_compaction_applied=bool(active.get("block_compaction_applied")),
            history=recent_history,
            wait_spins=wait_spins,
        )

        overlap_ratio = 0.0
        if active_list or candidate_list:
            overlap_ratio = len(set(active_list).intersection(candidate_list)) / max(1, len(set(active_list).union(candidate_list)))

        score_delta = round(candidate_metrics["score"] - active_metrics["score"], 4)
        confidence_delta = candidate_confidence - active_confidence
        max_wait_allowed = active_metrics["max_wait_allowed"]
        expired_wait = wait_spins >= max_wait_allowed
        active_neighbor = active_metrics["last_distance"] <= 1
        active_close = active_metrics["last_distance"] == 2
        candidate_closer = candidate_metrics["last_distance"] < active_metrics["last_distance"]
        candidate_stronger_region = candidate_metrics["touch_exact"] > active_metrics["touch_exact"] or candidate_metrics["touch_near"] > active_metrics["touch_near"]
        candidate_better_alternation = candidate_metrics["region_alignment"] >= (active_metrics["region_alignment"] + 0.2)
        candidate_switch_ready = (
            (candidate_closer and score_delta >= -2.0)
            or score_delta >= 8.0
            or (candidate_better_alternation and confidence_delta >= 0)
            or (candidate_stronger_region and candidate_closer)
        ) and overlap_ratio <= 0.75

        if active_neighbor:
            return {
                "action": "hold",
                "label": "Segurar",
                "reason": "Último número caiu dentro ou vizinho da sugestão ativa.",
                "score_delta": score_delta,
                "confidence_delta": int(confidence_delta),
                "overlap_ratio": round(overlap_ratio, 4),
                "saved_steps_estimate": 0,
                **active_metrics,
                "candidate_last_distance": candidate_metrics["last_distance"],
            }

        if active_close and not expired_wait:
            return {
                "action": "wait",
                "label": "Esperar",
                "reason": "Último número ficou a 2 casas da região. Compensa esperar sem trocar.",
                "score_delta": score_delta,
                "confidence_delta": int(confidence_delta),
                "overlap_ratio": round(overlap_ratio, 4),
                "saved_steps_estimate": 0,
                **active_metrics,
                "candidate_last_distance": candidate_metrics["last_distance"],
            }

        if candidate_switch_ready and (expired_wait or candidate_closer or candidate_better_alternation):
            saved_steps = max(1, min(max_attempts - attempts_used, 1 + max(0, active_metrics["last_distance"] - candidate_metrics["last_distance"])))
            return {
                "action": "switch",
                "label": "Trocar",
                "reason": "Sugestão atual ficou mais alinhada com a mesa e aproxima melhor da região ativa.",
                "score_delta": score_delta,
                "confidence_delta": int(confidence_delta),
                "overlap_ratio": round(overlap_ratio, 4),
                "saved_steps_estimate": int(saved_steps),
                **active_metrics,
                "candidate_last_distance": candidate_metrics["last_distance"],
                "candidate_region_alignment": candidate_metrics["region_alignment"],
            }

        if not expired_wait and active_metrics["last_distance"] >= 3:
            return {
                "action": "wait",
                "label": "Esperar",
                "reason": "Último número ficou longe da sugestão ativa e a mesa ainda não se alinhou.",
                "score_delta": score_delta,
                "confidence_delta": int(confidence_delta),
                "overlap_ratio": round(overlap_ratio, 4),
                "saved_steps_estimate": 0,
                **active_metrics,
                "candidate_last_distance": candidate_metrics["last_distance"],
            }

        if expired_wait and candidate_switch_ready:
            return {
                "action": "switch",
                "label": "Trocar",
                "reason": "Sinal ativo perdeu força com a espera e a nova sugestão oferece leitura melhor.",
                "score_delta": score_delta,
                "confidence_delta": int(confidence_delta),
                "overlap_ratio": round(overlap_ratio, 4),
                "saved_steps_estimate": 1,
                **active_metrics,
                "candidate_last_distance": candidate_metrics["last_distance"],
                "candidate_region_alignment": candidate_metrics["region_alignment"],
            }

        return {
            "action": "hold",
            "label": "Segurar",
            "reason": "A sugestão ativa ainda preserva relação suficiente com a mesa.",
            "score_delta": score_delta,
            "confidence_delta": int(confidence_delta),
            "overlap_ratio": round(overlap_ratio, 4),
            "saved_steps_estimate": 0,
            **active_metrics,
            "candidate_last_distance": candidate_metrics["last_distance"],
        }


final_suggestion_entry_intelligence = FinalSuggestionEntryIntelligenceService()

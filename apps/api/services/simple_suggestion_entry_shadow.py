from __future__ import annotations

from typing import Any, Dict, Mapping, Sequence


class SimpleSuggestionEntryShadowService:
    MODEL_VERSION = "simple-entry-shadow-v1"
    DEFAULT_MAX_ATTEMPTS = 4

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, float(value)))

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(default)

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    @staticmethod
    def _confidence_label(score: float | int) -> str:
        safe_score = max(0, min(100, int(round(float(score)))))
        if safe_score >= 75:
            return "Alta"
        if safe_score >= 60:
            return "Media"
        return "Baixa"

    def _normalize(self, value: float, upper_bound: float) -> float:
        if upper_bound <= 0:
            return 0.0
        return self._clamp(value / upper_bound, 0.0, 1.0)

    def _excess_pressure(self, observed: int, expected: float, window_size: int) -> float:
        safe_window = max(1, int(window_size))
        safe_expected = self._clamp(float(expected), 0.0, float(safe_window))
        safe_observed = max(0.0, min(float(safe_window), float(observed)))
        max_excess = max(1.0, float(safe_window) - safe_expected)
        return self._clamp((safe_observed - safe_expected) / max_excess, 0.0, 1.0)

    def _build_economics(self, suggestion_size: int, max_attempts: int) -> Dict[str, Any]:
        safe_size = max(0, min(37, int(suggestion_size)))
        safe_attempts = max(1, int(max_attempts))
        profits_by_attempt = {
            f"hit_{step}": int(36 - (safe_size * step))
            for step in range(1, safe_attempts + 1)
        }
        miss_loss = int(-(safe_size * safe_attempts))
        return {
            "suggestion_size": safe_size,
            "max_attempts": safe_attempts,
            "profits_by_attempt": profits_by_attempt,
            "miss_loss": miss_loss,
        }

    def unavailable(
        self,
        reason: str,
        *,
        suggestion_size: int = 0,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> Dict[str, Any]:
        economics = self._build_economics(suggestion_size, max_attempts)
        probabilities = {f"hit_{step}": 0.0 for step in range(1, economics["max_attempts"] + 1)}
        probabilities["miss"] = 1.0
        return {
            "enabled": True,
            "mode": "shadow",
            "model_version": self.MODEL_VERSION,
            "available": False,
            "entry_confidence": {"score": 0, "label": "Baixa"},
            "probabilities": probabilities,
            "late_hit_risk": 0.0,
            "expected_value": {"net_units": 0.0},
            "economics": economics,
            "features": {},
            "recommendation": {
                "action": "wait",
                "label": "Shadow indisponivel",
                "reason": str(reason or "Shadow indisponivel."),
            },
            "reasons": [str(reason or "Shadow indisponivel.")],
        }

    @staticmethod
    def _window_stats(
        values: Sequence[int],
        suggestion_set: set[int],
        start: int,
        size: int,
    ) -> Dict[str, Any]:
        window = [
            int(value)
            for value in values[start : start + max(1, int(size))]
            if 0 <= int(value) <= 36
        ]
        hits = sum(1 for value in window if value in suggestion_set)
        unique = len(set(window).intersection(suggestion_set))
        return {
            "window": window,
            "hits": int(hits),
            "unique": int(unique),
        }

    @staticmethod
    def _probability_map(probabilities_by_step: Dict[int, float], max_attempts: int) -> Dict[str, float]:
        result = {
            f"hit_{step}": round(float(probabilities_by_step.get(step, 0.0) or 0.0), 6)
            for step in range(1, max(1, int(max_attempts)) + 1)
        }
        total_hits = sum(result.values())
        result["miss"] = round(max(0.0, 1.0 - total_hits), 6)
        return result

    def evaluate(
        self,
        *,
        simple_payload: Mapping[str, Any] | None,
        history: Sequence[int] | None,
        from_index: int = 0,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> Dict[str, Any]:
        payload = dict(simple_payload or {})
        suggestion = [
            int(number)
            for number in (payload.get("list") or payload.get("suggestion") or [])
            if 0 <= int(number) <= 36
        ]
        safe_attempts = max(1, min(4, int(max_attempts)))
        economics = self._build_economics(len(suggestion), safe_attempts)
        if not suggestion:
            return self.unavailable(
                "Sugestao simples vazia para avaliacao shadow.",
                suggestion_size=0,
                max_attempts=safe_attempts,
            )

        safe_history = [int(n) for n in (history or []) if 0 <= int(n) <= 36]
        safe_from_index = max(0, min(int(from_index), max(0, len(safe_history) - 1)))
        anchor_history = safe_history[safe_from_index:]
        if len(anchor_history) < 2:
            return self.unavailable(
                "Historico insuficiente para entry shadow.",
                suggestion_size=len(suggestion),
                max_attempts=safe_attempts,
            )

        suggestion_set = set(suggestion)
        selected_details = payload.get("selected_number_details")
        if not isinstance(selected_details, list):
            selected_details = []

        top_support_count = self._safe_int(payload.get("top_support_count"), 0)
        min_support_count = self._safe_int(payload.get("min_support_count"), 0)
        avg_support_count = self._safe_float(payload.get("avg_support_count"), 0.0)
        top_weighted_support = self._safe_float(payload.get("top_weighted_support_score"), 0.0)
        min_weighted_support = self._safe_float(payload.get("min_weighted_support_score"), 0.0)
        avg_weighted_support = self._safe_float(payload.get("avg_weighted_support_score"), 0.0)
        pattern_count = self._safe_int(payload.get("pattern_count"), 0)

        if selected_details:
            support_scores = [self._safe_int(item.get("support_score"), 0) for item in selected_details]
            weighted_scores = [
                self._safe_float(item.get("weighted_support_score"), 0.0)
                for item in selected_details
            ]
            if top_support_count <= 0:
                top_support_count = support_scores[0]
            if min_support_count <= 0:
                min_support_count = support_scores[-1]
            if avg_support_count <= 0:
                avg_support_count = sum(support_scores) / len(support_scores)
            if top_weighted_support <= 0:
                top_weighted_support = weighted_scores[0]
            if min_weighted_support <= 0:
                min_weighted_support = weighted_scores[-1]
            if avg_weighted_support <= 0:
                avg_weighted_support = sum(weighted_scores) / len(weighted_scores)
            head_slice = support_scores[: max(1, len(support_scores) // 4)]
            tail_slice = support_scores[-max(1, len(support_scores) // 4) :]
        else:
            head_slice = [top_support_count] if top_support_count > 0 else []
            tail_slice = [min_support_count] if min_support_count > 0 else []

        head_support_avg = (sum(head_slice) / len(head_slice)) if head_slice else float(top_support_count)
        tail_support_avg = (sum(tail_slice) / len(tail_slice)) if tail_slice else float(min_support_count)

        pre_trigger = self._window_stats(anchor_history, suggestion_set, 1, 3)
        recent = self._window_stats(anchor_history, suggestion_set, 0, 5)
        extended = self._window_stats(anchor_history, suggestion_set, 0, 8)
        coverage_ratio = len(suggestion) / 37.0
        expected_pre_trigger_hits = 3.0 * coverage_ratio
        expected_recent_hits = 5.0 * coverage_ratio
        expected_extended_hits = 8.0 * coverage_ratio
        pre_trigger_hit_excess = self._excess_pressure(
            pre_trigger["hits"],
            expected_pre_trigger_hits,
            3,
        )
        recent_hit_excess = self._excess_pressure(
            recent["hits"],
            expected_recent_hits,
            5,
        )
        extended_hit_excess = self._excess_pressure(
            extended["hits"],
            expected_extended_hits,
            8,
        )

        support_quality = self._clamp(
            (self._normalize(avg_support_count, 6.0) * 0.35)
            + (self._normalize(top_support_count, 8.0) * 0.25)
            + (self._normalize(min_support_count, 4.0) * 0.20)
            + (self._normalize(pattern_count / max(1, len(suggestion)), 1.5) * 0.20),
            0.0,
            1.0,
        )
        tail_ratio = (min_support_count / max(1.0, float(top_support_count))) if top_support_count > 0 else 0.0
        weighted_tail_ratio = (
            min_weighted_support / max(0.001, float(top_weighted_support))
            if top_weighted_support > 0
            else 0.0
        )
        tail_health = self._clamp(
            (tail_ratio * 0.45)
            + (weighted_tail_ratio * 0.35)
            + (self._normalize(tail_support_avg, 4.0) * 0.20),
            0.0,
            1.0,
        )
        dispersion_penalty = self._clamp(
            ((1.0 - tail_ratio) * 0.55)
            + (self._normalize(max(0.0, head_support_avg - tail_support_avg), 4.0) * 0.45),
            0.0,
            1.0,
        )
        pressure_index = self._clamp(
            (pre_trigger_hit_excess * 0.34)
            + (recent_hit_excess * 0.36)
            + (extended_hit_excess * 0.20)
            + (self._normalize(pre_trigger["unique"], 3.0) * 0.10),
            0.0,
            1.0,
        )

        promptness_score = self._clamp(
            0.24
            + (support_quality * 0.42)
            + (tail_health * 0.22)
            - (pressure_index * 0.32)
            - (dispersion_penalty * 0.16),
            0.05,
            0.98,
        )
        coverage_score = self._clamp(
            0.45
            + (support_quality * 0.28)
            + (tail_health * 0.18)
            - (pressure_index * 0.18)
            - (dispersion_penalty * 0.08),
            0.05,
            0.99,
        )

        base_single_hit_rate = len(suggestion) / 37.0
        base_total_hit_rate = 1.0 - ((1.0 - base_single_hit_rate) ** safe_attempts)
        total_hit_rate = self._clamp(
            base_total_hit_rate
            + ((coverage_score - 0.5) * 0.10)
            - (max(0.0, pressure_index - 0.45) * 0.07),
            max(0.05, base_total_hit_rate - 0.12),
            0.995,
        )
        p_hit_1_share = self._clamp(
            0.56
            + (promptness_score * 0.20)
            + (support_quality * 0.08)
            + (tail_health * 0.05)
            - (pressure_index * 0.15)
            - (dispersion_penalty * 0.08),
            0.45,
            0.88,
        )
        p_hit_1 = total_hit_rate * p_hit_1_share
        late_mass = max(0.0, total_hit_rate - p_hit_1)
        delay_factor = self._clamp(
            0.45
            + (pressure_index * 0.40)
            + (dispersion_penalty * 0.25)
            - (support_quality * 0.20)
            - (tail_health * 0.10),
            0.0,
            1.0,
        )
        decay = self._clamp(0.55 + (delay_factor * 0.25), 0.40, 0.85)
        late_weights = {step: (decay ** (step - 2)) for step in range(2, safe_attempts + 1)}
        late_weight_sum = sum(late_weights.values()) or 1.0
        probabilities_by_step = {1: p_hit_1}
        for step in range(2, safe_attempts + 1):
            probabilities_by_step[step] = late_mass * (late_weights[step] / late_weight_sum)

        total_probability = sum(probabilities_by_step.values())
        if total_probability > 0.999999:
            scale = 0.999999 / total_probability
            probabilities_by_step = {
                step: probability * scale
                for step, probability in probabilities_by_step.items()
            }

        probabilities = self._probability_map(probabilities_by_step, safe_attempts)
        late_hit_risk = sum(
            float(probabilities.get(f"hit_{step}", 0.0) or 0.0)
            for step in range(2, safe_attempts + 1)
        )
        expected_value = 0.0
        for step in range(1, safe_attempts + 1):
            expected_value += float(probabilities.get(f"hit_{step}", 0.0) or 0.0) * float(
                economics["profits_by_attempt"][f"hit_{step}"]
            )
        expected_value += float(probabilities.get("miss", 0.0) or 0.0) * float(economics["miss_loss"])

        entry_score = int(round(self._clamp(
            (
                (float(probabilities.get("hit_1", 0.0) or 0.0) * 0.62)
                + ((1.0 - late_hit_risk) * 0.16)
                + (support_quality * 0.12)
                + ((1.0 - pressure_index) * 0.10)
            ) * 100.0,
            0.0,
            100.0,
        )))

        reasons: list[str] = []
        if support_quality >= 0.70:
            reasons.append("apoio estrutural forte no topo e na media da lista")
        elif support_quality <= 0.45:
            reasons.append("apoio estrutural limitado para a quantidade de numeros")
        if tail_health <= 0.42:
            reasons.append("cauda fraca nos numeros finais da sugestao")
        elif tail_health >= 0.65:
            reasons.append("cauda sustentada, com menos numeros de enchimento")
        if pressure_index >= 0.58:
            reasons.append("pressao recente alta sobre a regiao da aposta")
        elif pressure_index <= 0.25:
            reasons.append("contexto recente limpo antes da entrada")
        if pre_trigger["unique"] >= 3:
            reasons.append("overlap pre-trigger alto nos 3 giros anteriores")
        if float(probabilities.get("hit_1", 0.0) or 0.0) >= 0.72:
            reasons.append("probabilidade de primeiro tiro acima do corte operacional")
        if late_hit_risk >= 0.28:
            reasons.append("risco elevado de acerto tardio")
        if expected_value <= 0:
            reasons.append("valor esperado ainda negativo para esta entrada")

        high_pressure = (
            pressure_index >= 0.62
            or pre_trigger_hit_excess >= 0.65
            or recent_hit_excess >= 0.70
            or (pre_trigger["unique"] >= 3 and recent_hit_excess >= 0.55)
        )
        p_hit_1 = float(probabilities.get("hit_1", 0.0) or 0.0)
        if expected_value > 0 and p_hit_1 >= 0.72 and late_hit_risk <= 0.28 and not high_pressure:
            recommendation = {
                "action": "enter",
                "label": "Entrar",
                "reason": "Shadow sugere entrada imediata por hit@1 forte e risco tardio controlado.",
            }
        elif expected_value > -1.5 and p_hit_1 >= 0.64 and late_hit_risk <= 0.36:
            recommendation = {
                "action": "wait",
                "label": "Esperar",
                "reason": "Shadow ve potencial positivo, mas o timing ainda pede confirmacao.",
            }
        else:
            recommendation = {
                "action": "skip",
                "label": "Nao entrar",
                "reason": "Shadow identifica EV insuficiente ou risco tardio alto para a entrada.",
            }

        features = {
            "suggestion_size": len(suggestion),
            "pattern_count": pattern_count,
            "top_support_count": top_support_count,
            "avg_support_count": round(avg_support_count, 4),
            "min_support_count": min_support_count,
            "head_support_avg": round(head_support_avg, 4),
            "tail_support_avg": round(tail_support_avg, 4),
            "top_weighted_support_score": round(top_weighted_support, 6),
            "avg_weighted_support_score": round(avg_weighted_support, 6),
            "min_weighted_support_score": round(min_weighted_support, 6),
            "support_tail_ratio": round(tail_ratio, 6),
            "weighted_tail_ratio": round(weighted_tail_ratio, 6),
            "pre_trigger_hits": int(pre_trigger["hits"]),
            "pre_trigger_unique": int(pre_trigger["unique"]),
            "recent_hits": int(recent["hits"]),
            "recent_unique": int(recent["unique"]),
            "extended_hits": int(extended["hits"]),
            "extended_unique": int(extended["unique"]),
            "coverage_ratio": round(coverage_ratio, 6),
            "expected_pre_trigger_hits": round(expected_pre_trigger_hits, 6),
            "expected_recent_hits": round(expected_recent_hits, 6),
            "expected_extended_hits": round(expected_extended_hits, 6),
            "pre_trigger_hit_excess": round(pre_trigger_hit_excess, 6),
            "recent_hit_excess": round(recent_hit_excess, 6),
            "extended_hit_excess": round(extended_hit_excess, 6),
            "support_quality": round(support_quality, 6),
            "tail_health": round(tail_health, 6),
            "dispersion_penalty": round(dispersion_penalty, 6),
            "pressure_index": round(pressure_index, 6),
            "promptness_score": round(promptness_score, 6),
            "coverage_score": round(coverage_score, 6),
            "baseline_single_hit_rate": round(base_single_hit_rate, 6),
            "baseline_total_hit_rate": round(base_total_hit_rate, 6),
        }

        return {
            "enabled": True,
            "mode": "shadow",
            "model_version": self.MODEL_VERSION,
            "available": True,
            "entry_confidence": {
                "score": entry_score,
                "label": self._confidence_label(entry_score),
            },
            "probabilities": probabilities,
            "late_hit_risk": round(late_hit_risk, 6),
            "expected_value": {
                "net_units": round(expected_value, 6),
            },
            "economics": economics,
            "features": features,
            "recommendation": recommendation,
            "reasons": reasons,
        }


simple_suggestion_entry_shadow = SimpleSuggestionEntryShadowService()

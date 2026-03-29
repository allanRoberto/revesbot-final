from __future__ import annotations

import ast
import contextlib
import hashlib
import importlib.util
import inspect
import io
import json
import logging
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Set, TYPE_CHECKING

from api.helpers.utils.get_mirror import get_mirror
from api.patterns.evaluators import build_evaluator_registry
from api.services.base_suggestion import get_neighbors as get_wheel_neighbors
from api.services.confidence_calibration import ConfidenceCalibrationStore
from api.services.wheel_neighbors_5 import (
    WHEEL_NEIGHBORS_5_BASE_WEIGHT,
    WHEEL_NEIGHBORS_5_DEFAULT_HORIZON,
    WHEEL_NEIGHBORS_5_FEEDBACK_ANCHOR_SIZE,
    WHEEL_NEIGHBORS_5_RECENT_WINDOW,
    build_wheel_neighbors_5_result,
    get_wheel_neighbors_5_feedback_store,
    resolve_wheel_neighbors_5_horizon,
)

if TYPE_CHECKING:
    from api.services.pattern_correlation import CorrelationMatrix
    from api.services.pattern_decay import PatternDecayManager
    from api.services.suggestion_filter import SuggestionFilter

logger = logging.getLogger(__name__)
RED_NUMBERS = {
    1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36
}
BLACK_NUMBERS = {
    2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35
}
DOZEN_MAP: Dict[str, List[int]] = {
    "1st": list(range(1, 13)),   # 1-12
    "2nd": list(range(13, 25)),  # 13-24
    "3rd": list(range(25, 37)),  # 25-36
}
COLUMN_MAP: Dict[str, List[int]] = {
    "1st": [1, 4, 7, 10, 13, 16, 19, 22, 25, 28, 31, 34],
    "2nd": [2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32, 35],
    "3rd": [3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36],
}
EVEN_NUMBERS = {2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 32, 34, 36}
ODD_NUMBERS = {1, 3, 5, 7, 9, 11, 13, 15, 17, 19, 21, 23, 25, 27, 29, 31, 33, 35}
LOW_NUMBERS = set(range(1, 19))   # 1-18
HIGH_NUMBERS = set(range(19, 37)) # 19-36
SECTION_MAP: Dict[str, List[int]] = {
    "Jeu Zero": [12, 35, 3, 26, 0, 32, 15],
    "Voisins": [22, 18, 29, 7, 28, 12, 35, 3, 26, 0, 32, 15, 19, 4, 21, 2, 25],
    "Orphelins": [17, 34, 6, 1, 20, 14, 31, 9],
    "Tiers": [27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33],
}

WHEEL_ORDER: List[int] = [
    0,
    32,
    15,
    19,
    4,
    21,
    2,
    25,
    17,
    34,
    6,
    27,
    13,
    36,
    11,
    30,
    8,
    23,
    10,
    5,
    24,
    16,
    33,
    1,
    20,
    14,
    31,
    9,
    22,
    18,
    29,
    7,
    28,
    12,
    35,
    3,
    26,
]

# Famílias modulares para o padrão robusto (cavalos)
MODULAR_FAMILIES: Dict[str, Set[int]] = {
    "family_0369": {0, 3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36},
    "family_147": {1, 4, 7, 10, 13, 16, 19, 22, 25, 28, 31, 34},
    "family_258": {2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32, 35},
}

TERMINAL_GROUP_ROTATION_NUMBERS: Dict[str, List[int]] = {
    "A": [3, 6, 9, 13, 16, 19, 23, 26, 29, 33, 36],   # finais 3, 6, 9
    "B": [1, 4, 7, 11, 14, 17, 21, 24, 27, 31, 34],   # finais 1, 4, 7
    "C": [2, 5, 8, 12, 15, 18, 22, 25, 28, 32, 35],   # finais 2, 5, 8
}
TERMINAL_GROUP_ROTATION_BY_FINAL: Dict[int, str] = {
    1: "B",
    2: "C",
    3: "A",
    4: "B",
    5: "C",
    6: "A",
    7: "B",
    8: "C",
    9: "A",
}

# Controle operacional para desligar a negativacao sem remover os patterns.
NEGATIVE_PATTERNS_ENABLED = False


@dataclass
class PatternDefinition:
    id: str
    name: str
    version: str
    kind: str
    active: bool
    priority: int
    weight: float
    evaluator: str
    max_numbers: int
    params: Dict[str, Any]


@dataclass
class PatternContribution:
    pattern_id: str
    pattern_name: str
    version: str
    weight: float
    base_weight: float
    adaptive_multiplier: float
    numbers: List[int]
    explanation: str
    dynamic_multiplier: float = 1.0
    meta: Dict[str, Any] | None = None


class PatternEngine:
    """Loads pattern definitions from disk and computes an aggregated suggestion."""

    def __init__(self, patterns_dir: Path | None = None) -> None:
        base_dir = Path(__file__).resolve().parent.parent
        self._patterns_dir = patterns_dir or (base_dir / "patterns" / "definitions")
        self._patterns_cache: List[PatternDefinition] = []
        self._patterns_signature: tuple[tuple[str, int, int], ...] | None = None
        self._adaptive_weights_cache: Dict[str, tuple[Dict[str, float], List[Dict[str, Any]]]] = {}
        self._evaluator_registry: Dict[str, Callable[[List[int], List[int], int, PatternDefinition, int | None], Dict[str, Any]]] = (
            build_evaluator_registry(self)
        )
        # Cache para avaliações recentes
        self._evaluation_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_max_size = 32
        # Cache do bridge legacy
        # apps/api/services/pattern_engine.py -> project root em parents[3]
        self._project_root = Path(__file__).resolve().parents[3]
        apps_signals_root = self._project_root / "apps" / "signals"
        src_signals_root = self._project_root / "src" / "signals"
        self._legacy_signals_root = apps_signals_root if apps_signals_root.exists() else src_signals_root
        self._legacy_patterns_root = self._legacy_signals_root / "patterns"
        self._legacy_callable_cache: Dict[str, Callable[..., Any] | None] = {}
        self._legacy_paths_cache: Dict[str, tuple[tuple[tuple[str, int, int], ...], List[Path]]] = {}
        # Histórico de hit rates por padrão (para correlação e decay)
        self._pattern_hit_rates: Dict[str, float] = {}
        # Contador de misses consecutivos por padrão (para decay)
        self._pattern_miss_streak: Dict[str, int] = {}
        # Última volatilidade calculada (para threshold dinâmico)
        self._last_volatility: float = 0.5
        # Módulos de melhoria de assertividade (lazy loading)
        self._correlation_matrix: "CorrelationMatrix | None" = None
        self._pattern_decay: "PatternDecayManager | None" = None
        self._suggestion_filter: "SuggestionFilter | None" = None
        self._confidence_calibration = ConfidenceCalibrationStore()
        # Mapa de finais
        self._finals_map: Dict[int, List[int]] = {
            0: [0, 10, 20, 30],
            1: [1, 11, 21, 31],
            2: [2, 12, 22, 32],
            3: [3, 13, 23, 33],
            4: [4, 14, 24, 34],
            5: [5, 15, 25, 35],
            6: [6, 16, 26, 36],
            7: [7, 17, 27],
            8: [8, 18, 28],
            9: [9, 19, 29],
        }

    def evaluate(
        self,
        history: List[int],
        base_suggestion: List[int] | None = None,
        focus_number: int | None = None,
        from_index: int = 0,
        max_numbers: int = 18,
        legacy_confidence_score: float | None = None,
        use_adaptive_weights: bool = True,
        runtime_overrides: Dict[str, Dict[str, Any]] | None = None,
        weight_profile_id: str | None = None,
        weight_profile_weights: Dict[str, float] | None = None,
        use_fallback: bool = True,
    ) -> Dict[str, Any]:
        normalized_history = [self._normalize_number(n) for n in history if self._is_valid_number(n)]
        normalized_base = [self._normalize_number(n) for n in (base_suggestion or []) if self._is_valid_number(n)]
        normalized_profile_id = str(weight_profile_id or "").strip()
        normalized_profile_weights = {
            str(k): float(v)
            for k, v in dict(weight_profile_weights or {}).items()
            if str(k).strip()
        }

        # Cache de avaliações
        cache_key = self._build_cache_key(
            normalized_history,
            from_index,
            max_numbers,
            focus_number,
            base_suggestion=normalized_base,
            runtime_overrides=runtime_overrides,
            use_adaptive_weights=use_adaptive_weights,
            use_fallback=use_fallback,
            profile_id=normalized_profile_id,
            profile_weights=normalized_profile_weights,
        )
        if cache_key in self._evaluation_cache:
            return self._evaluation_cache[cache_key]

        if not normalized_history:
            return {
                "engine_version": "v1",
                "available": False,
                "suggestion": [],
                "explanation": "Historico vazio.",
                "contributions": [],
                "confidence": {"score": 0, "label": "Baixa"},
                "confidence_breakdown": self._empty_confidence_breakdown(),
                "negative_contributions": [],
                "pending_patterns": [],
                "number_details": [],
                "adaptive_weights": [],
            }

        # === THRESHOLD DINÂMICO GLOBAL ===
        # Calcular volatilidade e ajustar thresholds
        dynamic_threshold_mult = self.get_dynamic_threshold_multiplier(normalized_history)

        # Aplicar threshold dinâmico aos runtime_overrides
        if runtime_overrides is None:
            runtime_overrides = {}

        # Adicionar multiplicador de threshold para padrões que suportam
        for pattern_id in ["terminal_repeat_sum_neighbors", "color_streak_boost", "parity_streak_boost",
                          "high_low_streak_boost", "dozen_column_streak_boost"]:
            if pattern_id not in runtime_overrides:
                runtime_overrides[pattern_id] = {}
            runtime_overrides[pattern_id]["_dynamic_threshold_mult"] = dynamic_threshold_mult

        positive_contributions: List[PatternContribution] = []
        negative_contributions: List[PatternContribution] = []
        positive_scores: Dict[int, float] = defaultdict(float)
        negative_scores: Dict[int, float] = defaultdict(float)
        waiting_messages: List[str] = []
        pending_patterns: List[Dict[str, Any]] = []
        cap_candidates: List[int] = []
        enforce_groups: List[Dict[str, Any]] = []
        legacy_meta: Dict[str, Any] = {}
        definitions = self._load_patterns()
        negative_patterns_enabled = bool(NEGATIVE_PATTERNS_ENABLED)
        if use_adaptive_weights:
            adaptive_multipliers, adaptive_details = self._compute_adaptive_weights(
                definitions=definitions,
                history=normalized_history,
                base_suggestion=normalized_base,
                from_index=from_index,
            )
        else:
            adaptive_multipliers, adaptive_details = ({}, [])

        for definition in definitions:
            if definition.kind == "negative" and not negative_patterns_enabled:
                continue
            # Skip patterns disabled by decay system
            if self.is_pattern_disabled_by_decay(definition.id):
                continue

            profile_multiplier = float(normalized_profile_weights.get(definition.id, 1.0))
            profiled_weight = float(definition.weight) * profile_multiplier
            effective_definition = definition
            if runtime_overrides and isinstance(runtime_overrides, dict):
                raw_override = runtime_overrides.get(definition.id)
                if isinstance(raw_override, dict) and raw_override:
                    merged_params = dict(definition.params or {})
                    merged_params.update(raw_override)
                    effective_definition = PatternDefinition(
                        id=definition.id,
                        name=definition.name,
                        version=definition.version,
                        kind=definition.kind,
                        active=definition.active,
                        priority=definition.priority,
                        weight=profiled_weight,
                        evaluator=definition.evaluator,
                        max_numbers=definition.max_numbers,
                        params=merged_params,
                    )
            elif profiled_weight != float(definition.weight):
                effective_definition = PatternDefinition(
                    id=definition.id,
                    name=definition.name,
                    version=definition.version,
                    kind=definition.kind,
                    active=definition.active,
                    priority=definition.priority,
                    weight=profiled_weight,
                    evaluator=definition.evaluator,
                    max_numbers=definition.max_numbers,
                    params=dict(definition.params or {}),
                )
            runtime_profile_multiplier = profile_multiplier
            if abs(float(effective_definition.weight) - float(definition.weight)) > 1e-9:
                runtime_profile_multiplier = 1.0
            evaluator = self._evaluator_registry.get(definition.evaluator)
            if evaluator is None:
                logger.warning("Evaluator nao encontrado: %s", definition.evaluator)
                continue

            try:
                result = evaluator(normalized_history, normalized_base, from_index, effective_definition, focus_number)
            except Exception as exc:  # pragma: no cover
                logger.exception("Erro executando pattern %s: %s", definition.id, exc)
                continue

            raw_pending = result.get("pending_items") if isinstance(result, dict) else None
            if isinstance(raw_pending, list) and raw_pending:
                pending_patterns.append(
                    {
                        "pattern_id": effective_definition.id,
                        "pattern_name": effective_definition.name,
                        "version": effective_definition.version,
                        "items": raw_pending,
                    }
                )
            raw_meta = result.get("meta") if isinstance(result, dict) else None
            if isinstance(raw_meta, dict):
                legacy_meta.update(raw_meta)
            result_dynamic_multiplier = float(result.get("dynamic_multiplier", 1.0) or 1.0)

            explanation = str(result.get("explanation", "Pattern ativo.")).strip()
            raw_split = result.get("split_contributions") if isinstance(result, dict) else None
            if isinstance(raw_split, list) and raw_split:
                split_added = False
                for idx, item in enumerate(raw_split, start=1):
                    if not isinstance(item, dict):
                        continue

                    item_numbers = [
                        self._normalize_number(n)
                        for n in item.get("numbers", [])
                        if self._is_valid_number(n)
                    ]
                    item_explanation = str(item.get("explanation", explanation or "Pattern ativo.")).strip()
                    if not item_numbers:
                        if item_explanation:
                            waiting_messages.append(item_explanation)
                        continue

                    item_pattern_id = str(item.get("pattern_id", "")).strip() or f"{definition.id}_{idx}"
                    item_pattern_name = str(item.get("pattern_name", "")).strip() or f"{definition.name} #{idx}"
                    item_base_weight = float(item.get("weight", effective_definition.weight)) * runtime_profile_multiplier
                    item_adaptive = adaptive_multipliers.get(definition.id, 1.0)
                    item_dynamic = float(item.get("dynamic_multiplier", result_dynamic_multiplier) or 1.0)
                    item_meta = item.get("meta") if isinstance(item.get("meta"), dict) else raw_meta
                    item_weight = item_base_weight * item_adaptive * item_dynamic

                    contribution = PatternContribution(
                        pattern_id=item_pattern_id,
                        pattern_name=item_pattern_name,
                        version=definition.version,
                        weight=item_weight,
                        base_weight=item_base_weight,
                        adaptive_multiplier=item_adaptive,
                        numbers=sorted(set(item_numbers)),
                        explanation=item_explanation,
                        dynamic_multiplier=item_dynamic,
                        meta=dict(item_meta) if isinstance(item_meta, dict) else None,
                    )
                    if definition.kind == "negative":
                        negative_contributions.append(contribution)
                        cap = effective_definition.params.get("suggestion_cap")
                        if isinstance(cap, int) and cap > 0:
                            cap_candidates.append(cap)
                    else:
                        positive_contributions.append(contribution)
                        if bool(effective_definition.params.get("enforce_presence", False)):
                            min_keep = int(effective_definition.params.get("min_keep", 1))
                            if min_keep > 0:
                                enforce_groups.append(
                                    {
                                        "pattern_id": item_pattern_id,
                                        "min_keep": min_keep,
                                        "numbers": sorted(set(item_numbers)),
                                    }
                                )

                    local_scores = item.get("scores") or {}
                    target = negative_scores if definition.kind == "negative" else positive_scores
                    for n in contribution.numbers:
                        local_score = float(local_scores.get(n, 1.0))
                        correlation_boost = self.get_pattern_correlation_boost(item_pattern_id)
                        decay_multiplier = self.get_decay_multiplier(item_pattern_id)
                        effective_weight = (
                            item_base_weight
                            * item_adaptive
                            * item_dynamic
                            * correlation_boost
                            * decay_multiplier
                        )
                        target[n] += max(0.01, effective_weight * local_score)

                    split_added = True

                if split_added:
                    continue

            numbers = [self._normalize_number(n) for n in result.get("numbers", []) if self._is_valid_number(n)]
            if not numbers:
                if explanation:
                    waiting_messages.append(explanation)
                continue

            contribution = PatternContribution(
                pattern_id=definition.id,
                pattern_name=definition.name,
                version=definition.version,
                weight=(
                    effective_definition.weight
                    * adaptive_multipliers.get(definition.id, 1.0)
                    * runtime_profile_multiplier
                    * result_dynamic_multiplier
                ),
                base_weight=(effective_definition.weight * runtime_profile_multiplier),
                adaptive_multiplier=adaptive_multipliers.get(definition.id, 1.0),
                numbers=sorted(set(numbers)),
                explanation=explanation,
                dynamic_multiplier=result_dynamic_multiplier,
                meta=dict(raw_meta) if isinstance(raw_meta, dict) else None,
            )
            if definition.kind == "negative":
                negative_contributions.append(contribution)
                cap = effective_definition.params.get("suggestion_cap")
                if isinstance(cap, int) and cap > 0:
                    cap_candidates.append(cap)
            else:
                positive_contributions.append(contribution)
                if bool(effective_definition.params.get("enforce_presence", False)):
                    min_keep = int(effective_definition.params.get("min_keep", 1))
                    if min_keep > 0:
                        enforce_groups.append(
                            {
                                "pattern_id": definition.id,
                                "min_keep": min_keep,
                                "numbers": sorted(set(numbers)),
                            }
                        )

            local_scores = result.get("scores") or {}
            target = negative_scores if definition.kind == "negative" else positive_scores
            for n in numbers:
                local_score = float(local_scores.get(n, 1.0))
                # Aplicar correlação (hit rate histórico do padrão)
                correlation_boost = self.get_pattern_correlation_boost(definition.id)
                # Aplicar decay multiplier do módulo de decay
                decay_multiplier = self.get_decay_multiplier(definition.id)
                effective_weight = (
                    effective_definition.weight
                    * adaptive_multipliers.get(definition.id, 1.0)
                    * runtime_profile_multiplier
                    * result_dynamic_multiplier
                    * correlation_boost
                    * decay_multiplier
                )
                target[n] += max(0.01, effective_weight * local_score)

        # Fallback inteligente se nenhum padrão positivo ativou
        if not positive_contributions and use_fallback:
            fallback_result = self._get_fallback_suggestion(
                history=normalized_history,
                from_index=from_index,
                max_numbers=max_numbers,
            )
            if fallback_result.get("numbers"):
                # Usar resultado do fallback como contribuição
                fallback_numbers = fallback_result.get("numbers", [])
                fallback_scores = fallback_result.get("scores", {})
                for n in fallback_numbers:
                    positive_scores[n] = fallback_scores.get(n, 0.5)
                positive_contributions.append(
                    PatternContribution(
                        pattern_id="fallback_strategy",
                        pattern_name="Fallback Inteligente",
                        version="1.0.0",
                        weight=1.5,
                        base_weight=1.5,
                        adaptive_multiplier=1.0,
                        numbers=fallback_numbers,
                        explanation=fallback_result.get("explanation", "Fallback ativo"),
                        dynamic_multiplier=1.0,
                    )
                )

        if not positive_contributions:
            if waiting_messages:
                msg = " | ".join(dict.fromkeys(waiting_messages))
                result_empty = {
                    "engine_version": "v1",
                    "available": False,
                    "suggestion": [],
                    "explanation": msg,
                    "contributions": [],
                    "confidence": {"score": 0, "label": "Baixa"},
                    "confidence_breakdown": self._empty_confidence_breakdown(),
                    "negative_contributions": [self._serialize_contribution(c) for c in negative_contributions],
                    "pending_patterns": pending_patterns,
                    "number_details": [],
                    "adaptive_weights": adaptive_details,
                }
                self._save_to_cache(cache_key, result_empty)
                return result_empty
            result_empty2 = {
                "engine_version": "v1",
                "available": False,
                "suggestion": [],
                "explanation": "Nenhum padrao ativo identificou sugestao para o momento.",
                "contributions": [],
                "confidence": {"score": 0, "label": "Baixa"},
                "confidence_breakdown": self._empty_confidence_breakdown(),
                "negative_contributions": [self._serialize_contribution(c) for c in negative_contributions],
                "pending_patterns": pending_patterns,
                "number_details": [],
                "adaptive_weights": adaptive_details,
            }
            self._save_to_cache(cache_key, result_empty2)
            return result_empty2

        def _build_ranked_entries(ps: Dict[int, float], ns: Dict[int, float]) -> List[tuple[int, float, float, float]]:
            entries: List[tuple[int, float, float, float]] = []
            for n in set(ps.keys()).union(ns.keys()):
                p = float(ps.get(n, 0.0))
                ng = float(ns.get(n, 0.0))
                final_score = p - ng
                if p <= 0:
                    continue
                if final_score <= 0:
                    continue
                entries.append((n, final_score, p, ng))
            return entries

        def _select_entries(
            ranked_entries: List[tuple[int, float, float, float]]
        ) -> tuple[List[tuple[int, float, float, float]], int]:
            ranked = sorted(ranked_entries, key=lambda item: (-item[1], -item[2], item[0]))
            final_cap = max(1, min([max_numbers] + cap_candidates)) if cap_candidates else max(1, max_numbers)
            ranked_lookup = {n: (n, fs, ps, ngs) for n, fs, ps, ngs in ranked}
            selected_entries: List[tuple[int, float, float, float]] = []
            selected_nums: set[int] = set()

            for group in enforce_groups:
                keep = max(1, int(group["min_keep"]))
                group_candidates = [
                    ranked_lookup[n]
                    for n in group["numbers"]
                    if n in ranked_lookup
                ]
                group_candidates.sort(key=lambda item: (-item[1], -item[2], item[0]))
                for entry in group_candidates[:keep]:
                    n = entry[0]
                    if n in selected_nums:
                        continue
                    selected_entries.append(entry)
                    selected_nums.add(n)
                    if len(selected_entries) >= final_cap:
                        break
                if len(selected_entries) >= final_cap:
                    break

            for entry in ranked:
                if len(selected_entries) >= final_cap:
                    break
                n = entry[0]
                if n in selected_nums:
                    continue
                selected_entries.append(entry)
                selected_nums.add(n)

            filtered_count = len(ranked_entries) - len(selected_entries)
            return selected_entries, filtered_count

        # === NORMALIZAÇÃO DE SCORES ===
        # Normaliza scores positivos e negativos para evitar que um padrão domine
        if positive_scores:
            normalized_positive = self.normalize_scores(dict(positive_scores))
            # Manter proporção mas em escala normalizada (multiplicar por fator para manter magnitude)
            scale_factor = max(positive_scores.values()) if positive_scores else 1.0
            positive_floor = 0.05
            for n in positive_scores:
                positive_scores[n] = (
                    positive_floor + (normalized_positive.get(n, 0) * (1.0 - positive_floor))
                ) * scale_factor

        if negative_scores:
            normalized_negative = self.normalize_scores(dict(negative_scores))
            scale_factor = max(negative_scores.values()) if negative_scores else 1.0
            for n in negative_scores:
                negative_scores[n] = normalized_negative.get(n, 0) * scale_factor

        scored_candidates = _build_ranked_entries(positive_scores, negative_scores)

        # === BOOST DINÂMICO BASEADO NA CONFIANÇA ===
        # Identifica números dos padrões imediatos (alta prioridade)
        immediate_pattern_ids = {
            "terminal_repeat_sum_neighbors",
            "skipped_sequence_target_neighbors",
            "terminal_alternation_target_neighbors",
            "anchor_return_target_neighbors_mirrors",
        }
        immediate_numbers: set[int] = set()
        for c in positive_contributions:
            if c.pattern_id in immediate_pattern_ids:
                immediate_numbers.update(c.numbers)

        # Calcula confiança preliminar para decidir o boost
        if scored_candidates and immediate_numbers:
            preliminary_confidence = self._build_confidence(
                scored_candidates[:max_numbers], len(positive_contributions), len(negative_contributions)
            )
            preliminary_score = int(preliminary_confidence.get("score", 0) or 0)

            # Boost contínuo a partir de 50% - função linear suave
            if preliminary_score >= 50:
                # Boost varia de 1.0 (conf=50) até 1.40 (conf=100)
                boost_factor = 1.0 + ((preliminary_score - 50) / 50) * 0.40
                boost_factor = min(1.40, max(1.0, boost_factor))

                boosted_candidates: List[tuple[int, float, float, float]] = []
                for n, final_score, pos_score, neg_score in scored_candidates:
                    if n in immediate_numbers:
                        # Aplica boost no score final
                        new_final = final_score * boost_factor
                        new_pos = pos_score * boost_factor
                        boosted_candidates.append((n, new_final, new_pos, neg_score))
                    else:
                        boosted_candidates.append((n, final_score, pos_score, neg_score))
                scored_candidates = boosted_candidates

        if not scored_candidates:
            result_filtered = {
                "engine_version": "v1",
                "available": False,
                "suggestion": [],
                "explanation": "Todos os numeros candidatos foram negativados pelos filtros.",
                "contributions": [self._serialize_contribution(c) for c in positive_contributions],
                "confidence": {"score": 0, "label": "Baixa"},
                "confidence_breakdown": self._empty_confidence_breakdown(),
                "negative_contributions": [self._serialize_contribution(c) for c in negative_contributions],
                "pending_patterns": pending_patterns,
                "number_details": [],
                "adaptive_weights": adaptive_details,
            }
            self._save_to_cache(cache_key, result_filtered)
            return result_filtered

        selected_entries, filtered_count = _select_entries(scored_candidates)
        confidence_api_raw_base = self._build_confidence(
            selected_entries, len(positive_contributions), len(negative_contributions)
        )
        confidence_context = self._build_confidence_context(
            selected_entries=selected_entries,
            positive_contributions=positive_contributions,
        )
        confidence_api_raw = self._rebalance_api_confidence(
            base_confidence=confidence_api_raw_base,
            context=confidence_context,
        )
        legacy_conf_score = int(legacy_meta.get("legacy_confidence_score", 0) or 0)
        legacy_numbers = legacy_meta.get("legacy_numbers", []) or []

        # Mantém ordem de ranking calculada pelo motor; apresentação pode ordenar no frontend.
        suggestion = [num for num, _, _, _ in selected_entries]
        selected_set = set(suggestion)
        ranked_map = {n: {"net_score": fs, "positive_score": ps, "negative_score": ng} for n, fs, ps, ng in scored_candidates}
        positive_patterns_by_number: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        negative_patterns_by_number: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        for c in positive_contributions:
            for n in c.numbers:
                positive_patterns_by_number[n].append(
                    {
                        "pattern_id": c.pattern_id,
                        "pattern_name": c.pattern_name,
                        "weight": c.weight,
                        "base_weight": c.base_weight,
                        "adaptive_multiplier": c.adaptive_multiplier,
                        "dynamic_multiplier": c.dynamic_multiplier,
                    }
                )
        for c in negative_contributions:
            for n in c.numbers:
                negative_patterns_by_number[n].append(
                    {
                        "pattern_id": c.pattern_id,
                        "pattern_name": c.pattern_name,
                        "weight": c.weight,
                        "base_weight": c.base_weight,
                        "adaptive_multiplier": c.adaptive_multiplier,
                        "dynamic_multiplier": c.dynamic_multiplier,
                    }
                )
        number_details = []
        for n, scores in sorted(ranked_map.items(), key=lambda item: (-item[1]["net_score"], item[0])):
            number_details.append(
                {
                    "number": int(n),
                    "selected": int(n) in selected_set,
                    "net_score": round(float(scores["net_score"]), 4),
                    "positive_score": round(float(scores["positive_score"]), 4),
                    "negative_score": round(float(scores["negative_score"]), 4),
                    "positive_patterns": positive_patterns_by_number.get(int(n), []),
                    "negative_patterns": negative_patterns_by_number.get(int(n), []),
                }
            )

        confidence, confidence_breakdown = self._merge_confidence(
            confidence_api_raw,
            legacy_conf_score,
            suggestion=suggestion,
            legacy_numbers=legacy_numbers,
            context=confidence_context,
            api_raw_base_score=int(confidence_api_raw_base.get("score", 0) or 0),
        )
        confidence_v2, confidence_v2_breakdown = self._build_confidence_v2_shadow(
            selected_entries=selected_entries,
            positive_count=len(positive_contributions),
            legacy_score=legacy_conf_score,
            suggestion=suggestion,
            legacy_numbers=legacy_numbers,
            context=confidence_context,
        )
        confidence_breakdown.update(confidence_v2_breakdown)
        confidence_breakdown["confidence_v2_shadow"] = confidence_v2

        # Apply suggestion filter to decide if signal should be emitted
        filter_result = self.apply_suggestion_filter(
            positive_contributions=[
                {"pattern_id": c.pattern_id, "numbers": c.numbers, "weight": c.weight}
                for c in positive_contributions
            ],
            confidence_context=confidence_context,
            confidence_score=int(confidence.get("score", 0) or 0),
        )

        # If filter fails, mark as unavailable with reason
        if not filter_result.get("passed", True):
            filter_reason = filter_result.get("reason", "Filtro de qualidade nao atendido")
            result_filtered_by_quality = {
                "engine_version": "v1",
                "available": False,
                "suggestion": [],
                "explanation": f"Sinal filtrado: {filter_reason}",
                "filter_reason": filter_reason,
                "filter_details": filter_result.get("filter_details", {}),
                "contributions": [self._serialize_contribution(c) for c in positive_contributions],
                "confidence": confidence,
                "confidence_breakdown": confidence_breakdown,
                "negative_contributions": [self._serialize_contribution(c) for c in negative_contributions],
                "pending_patterns": pending_patterns,
                "number_details": number_details,
                "adaptive_weights": adaptive_details,
            }
            self._save_to_cache(cache_key, result_filtered_by_quality)
            return result_filtered_by_quality

        final_result = {
            "engine_version": "v1",
            "available": True,
            "suggestion": suggestion,
            "explanation": (
                f"{len(positive_contributions)} padrao(es) positivos contribuiram para a sugestao. "
                f"{len(negative_contributions)} padrao(es) negativos aplicados."
                + (f" {filtered_count} numero(s) excedente(s) filtrados por ranking." if filtered_count > 0 else "")
            ),
            "confidence": confidence,
            "confidence_breakdown": confidence_breakdown,
            "contributions": [self._serialize_contribution(c) for c in positive_contributions],
            "negative_contributions": [self._serialize_contribution(c) for c in negative_contributions],
            "pending_patterns": pending_patterns,
            "number_details": number_details,
            "adaptive_weights": adaptive_details,
        }
        self._save_to_cache(cache_key, final_result)
        return final_result

    def _build_cache_key(
        self,
        history: List[int],
        from_index: int,
        max_numbers: int,
        focus_number: int | None,
        base_suggestion: List[int] | None = None,
        runtime_overrides: Dict[str, Dict[str, Any]] | None = None,
        use_adaptive_weights: bool = True,
        use_fallback: bool = True,
        profile_id: str = "",
        profile_weights: Dict[str, float] | None = None,
    ) -> str:
        """Gera chave única para cache baseada nos parâmetros."""
        # Usar apenas os últimos 20 números para a chave (suficiente para os padrões)
        relevant_history = history[from_index:from_index + 20]
        history_str = ",".join(str(n) for n in relevant_history)
        base_signature = ",".join(str(int(n)) for n in (base_suggestion or []))
        runtime_signature = ""
        if isinstance(runtime_overrides, dict) and runtime_overrides:
            runtime_items = []
            for pattern_id, params in sorted(runtime_overrides.items(), key=lambda item: item[0]):
                if not isinstance(params, dict):
                    continue
                param_signature = ",".join(
                    f"{key}:{repr(params[key])}"
                    for key in sorted(params.keys())
                )
                runtime_items.append(f"{pattern_id}=>{param_signature}")
            runtime_signature = "|".join(runtime_items)
        profile_signature = profile_id.strip()
        if not profile_signature and profile_weights:
            profile_signature = ",".join(
                f"{key}:{round(float(value), 6)}"
                for key, value in sorted(profile_weights.items(), key=lambda item: item[0])
            )
        return (
            f"{history_str}|{from_index}|{max_numbers}|{focus_number}|"
            f"base:{base_signature}|runtime:{runtime_signature}|"
            f"adaptive:{int(bool(use_adaptive_weights))}|fallback:{int(bool(use_fallback))}|"
            f"profile:{profile_signature}|negative:{int(bool(NEGATIVE_PATTERNS_ENABLED))}"
        )

    def _save_to_cache(self, key: str, result: Dict[str, Any]) -> None:
        """Salva resultado no cache com limite de tamanho."""
        if len(self._evaluation_cache) >= self._cache_max_size:
            # Remover entrada mais antiga
            oldest_key = next(iter(self._evaluation_cache))
            del self._evaluation_cache[oldest_key]
        self._evaluation_cache[key] = result

    def clear_cache(self) -> None:
        """Limpa o cache de avaliações."""
        self._evaluation_cache.clear()

    @staticmethod
    def _serialize_contribution(contribution: PatternContribution) -> Dict[str, Any]:
        payload = {
            "pattern_id": contribution.pattern_id,
            "pattern_name": contribution.pattern_name,
            "version": contribution.version,
            "weight": contribution.weight,
            "base_weight": contribution.base_weight,
            "adaptive_multiplier": contribution.adaptive_multiplier,
            "dynamic_multiplier": contribution.dynamic_multiplier,
            "numbers": contribution.numbers,
            "explanation": contribution.explanation,
        }
        if isinstance(contribution.meta, dict) and contribution.meta:
            payload["meta"] = contribution.meta
        return payload

    @classmethod
    def _empty_confidence_breakdown(cls) -> Dict[str, Any]:
        return {
            "api_raw": 0,
            "legacy": 0,
            "merged": 0,
            "overlap_ratio": 0,
            "structural_raw_v2": 0,
            "merged_raw_v2": 0,
            "calibrated_confidence_v2": 0,
            "calibration_bucket": "00-09",
            "calibration_bucket_hit4": 0.0,
            "calibration_reliability": 0.0,
            "confidence_v2_shadow": {"score": 0, "label": cls._confidence_label(0)},
        }

    @staticmethod
    def _build_confidence(
        selected_entries: List[tuple[int, float, float, float]],
        positive_count: int,
        negative_count: int,
    ) -> Dict[str, Any]:
        if not selected_entries:
            return {"score": 0, "label": "Baixa"}

        avg_final = sum(item[1] for item in selected_entries) / len(selected_entries)
        total_positive = sum(item[2] for item in selected_entries)
        total_negative = sum(item[3] for item in selected_entries)
        neg_ratio = (total_negative / total_positive) if total_positive > 0 else 1.0

        score_component = (avg_final / (avg_final + 1.0)) * 60.0
        support_component = min(1.0, positive_count / 4.0) * 30.0
        penalty_component = max(0.0, 1.0 - min(1.0, neg_ratio)) * 10.0
        score = int(round(max(0.0, min(100.0, score_component + support_component + penalty_component))))

        if score >= 75:
            label = "Alta"
        elif score >= 50:
            label = "Media"
        else:
            label = "Baixa"
        return {
            "score": score,
            "label": label,
        }

    @staticmethod
    def _confidence_label(score: float | int) -> str:
        safe_score = max(0, min(100, int(round(float(score)))))
        if safe_score >= 75:
            return "Alta"
        if safe_score >= 50:
            return "Media"
        return "Baixa"

    def _build_confidence_v2_shadow(
        self,
        selected_entries: List[tuple[int, float, float, float]],
        positive_count: int,
        legacy_score: int,
        suggestion: List[int],
        legacy_numbers: List[int],
        context: Dict[str, float] | None = None,
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        structural = self._build_structural_confidence_v2(
            selected_entries=selected_entries,
            positive_count=positive_count,
            context=context,
        )
        merged_v2 = self._merge_confidence_v2(
            structural_score=int(structural.get("score", 0) or 0),
            legacy_score=legacy_score,
            suggestion=suggestion,
            legacy_numbers=legacy_numbers,
        )
        calibration = self._confidence_calibration.calibrate(int(merged_v2.get("score", 0) or 0))
        calibrated_score = int(calibration.get("score", 0) or 0)
        confidence_v2 = {
            "score": calibrated_score,
            "label": self._confidence_label(calibrated_score),
        }
        breakdown = {
            "structural_raw_v2": round(float(structural.get("score", 0) or 0), 3),
            "merged_raw_v2": round(float(merged_v2.get("score", 0) or 0), 3),
            "calibrated_confidence_v2": calibrated_score,
            "calibration_bucket": str(calibration.get("bucket", "00-09")),
            "calibration_bucket_hit4": round(float(calibration.get("hit_rate", 0.0) or 0.0), 4),
            "calibration_bucket_promptness_v2": round(float(calibration.get("promptness_score", 0.0) or 0.0), 4),
            "calibration_reliability": round(float(calibration.get("reliability", 0.0) or 0.0), 4),
            "calibration_avg_first_hit_attempt_v2": calibration.get("avg_first_hit_attempt"),
            "calibration_bucket_hit1": round(float((calibration.get("attempt_rates") or {}).get("hit@1", 0.0) or 0.0), 4),
            "calibration_bucket_hit2": round(float((calibration.get("attempt_rates") or {}).get("hit@2", 0.0) or 0.0), 4),
            "calibration_bucket_hit8": round(float((calibration.get("attempt_rates") or {}).get("hit@8", 0.0) or 0.0), 4),
            "calibration_bucket_hit10": round(float((calibration.get("attempt_rates") or {}).get("hit@10", 0.0) or 0.0), 4),
            "confidence_v2_api_weight": round(float(merged_v2.get("api_weight", 1.0) or 1.0), 4),
            "confidence_v2_legacy_weight": round(float(merged_v2.get("legacy_weight", 0.0) or 0.0), 4),
            "confidence_v2_overlap_ratio": round(float(merged_v2.get("overlap_ratio", 0.0) or 0.0), 4),
        }
        return confidence_v2, breakdown

    @classmethod
    def _build_structural_confidence_v2(
        cls,
        selected_entries: List[tuple[int, float, float, float]],
        positive_count: int,
        context: Dict[str, float] | None = None,
    ) -> Dict[str, Any]:
        if not selected_entries:
            return {"score": 0, "label": cls._confidence_label(0)}

        ctx = context or {}
        avg_final = sum(item[1] for item in selected_entries) / len(selected_entries)
        score_strength = avg_final / (avg_final + 1.0) if avg_final > 0 else 0.0
        support_strength = min(positive_count, 4) / 4.0
        consensus_score = max(0.0, min(1.0, float(ctx.get("consensus_score", 0.0))))
        weighted_consensus = max(0.0, min(1.0, float(ctx.get("weighted_consensus", 0.0))))
        immediate_score = max(0.0, min(1.0, float(ctx.get("immediate_score", 0.0))))
        pattern_diversity = max(0.0, min(1.0, float(ctx.get("pattern_diversity", 0.0))))
        negative_pressure = max(0.0, min(1.0, float(ctx.get("negative_pressure", 1.0))))
        pressure_health = 1.0 - negative_pressure
        consensus_blend = (
            (consensus_score * 0.30)
            + (weighted_consensus * 0.55)
            + (immediate_score * 0.15)
        )
        score = 100.0 * (
            (score_strength * 0.46)
            + (support_strength * 0.18)
            + (consensus_blend * 0.18)
            + (pressure_health * 0.10)
            + (pattern_diversity * 0.08)
        )
        safe_score = max(0, min(100, int(round(score))))
        return {"score": safe_score, "label": cls._confidence_label(safe_score)}

    @classmethod
    def _merge_confidence_v2(
        cls,
        structural_score: int,
        legacy_score: int,
        suggestion: List[int],
        legacy_numbers: List[int],
    ) -> Dict[str, Any]:
        structural = max(0, min(100, int(structural_score or 0)))
        legacy = max(0, min(100, int(legacy_score or 0)))
        suggestion_set = set(suggestion or [])
        legacy_set = set(int(n) for n in (legacy_numbers or []) if isinstance(n, int) or str(n).isdigit())
        overlap_ratio = (len(suggestion_set.intersection(legacy_set)) / len(suggestion_set)) if suggestion_set else 0.0
        has_legacy_signal = legacy > 0 or bool(legacy_set)
        legacy_weight = 0.0
        if has_legacy_signal:
            legacy_weight = max(0.12, min(0.28, 0.12 + (overlap_ratio * 0.16)))
        api_weight = 1.0 - legacy_weight
        merged = int(round((structural * api_weight) + (legacy * legacy_weight)))
        merged = max(0, min(100, merged))
        return {
            "score": merged,
            "label": cls._confidence_label(merged),
            "api_weight": api_weight,
            "legacy_weight": legacy_weight,
            "overlap_ratio": overlap_ratio,
        }

    @staticmethod
    def _merge_confidence(
        api_raw: Dict[str, Any],
        legacy_score: int,
        suggestion: List[int],
        legacy_numbers: List[int],
        context: Dict[str, float] | None = None,
        api_raw_base_score: int | None = None,
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        api_score = int(api_raw.get("score", 0) or 0)
        legacy = max(0, min(100, int(legacy_score or 0)))
        suggestion_set = set(suggestion or [])
        legacy_set = set(int(n) for n in (legacy_numbers or []) if isinstance(n, int) or str(n).isdigit())
        overlap_ratio = (len(suggestion_set.intersection(legacy_set)) / len(suggestion_set)) if suggestion_set else 0.0

        ctx = context or {}
        consensus_score = max(0.0, min(1.0, float(ctx.get("consensus_score", 0.0))))
        immediate_score = max(0.0, min(1.0, float(ctx.get("immediate_score", 0.0))))
        negative_pressure = max(0.0, min(1.0, float(ctx.get("negative_pressure", 0.0))))
        weighted_consensus = max(0.0, min(1.0, float(ctx.get("weighted_consensus", 0.0))))
        pattern_diversity = max(0.0, min(1.0, float(ctx.get("pattern_diversity", 0.0))))

        # Peso da API aumenta com consenso ponderado e diversidade
        api_weight = (
            0.65
            + (consensus_score * 0.10)
            + (weighted_consensus * 0.15)
            + (immediate_score * 0.08)
            + (pattern_diversity * 0.07)
            - (negative_pressure * 0.10)
        )
        api_weight = max(0.50, min(0.92, api_weight))
        legacy_weight = 1.0 - api_weight

        merged = int(
            round(
                (api_score * api_weight)
                + (legacy * legacy_weight)
                + (overlap_ratio * 8.0)
                + (consensus_score * 4.0)
                + (weighted_consensus * 6.0)
                + (immediate_score * 4.0)
                + (pattern_diversity * 4.0)
                - (negative_pressure * 6.0)
            )
        )
        merged = max(0, min(100, merged))
        if merged >= 75:
            label = "Alta"
        elif merged >= 50:
            label = "Media"
        else:
            label = "Baixa"
        return (
            {"score": merged, "label": label},
            {
                "api_raw_base": max(0, min(100, int(api_raw_base_score if api_raw_base_score is not None else api_score))),
                "api_raw": api_score,
                "legacy": legacy,
                "merged": merged,
                "overlap_ratio": round(overlap_ratio, 3),
                "consensus_score": round(consensus_score, 3),
                "weighted_consensus": round(weighted_consensus, 3),
                "immediate_score": round(immediate_score, 3),
                "pattern_diversity": round(pattern_diversity, 3),
                "negative_pressure": round(negative_pressure, 3),
                "api_weight": round(api_weight, 3),
                "legacy_weight": round(legacy_weight, 3),
            },
        )

    @staticmethod
    def _build_confidence_context(
        selected_entries: List[tuple[int, float, float, float]],
        positive_contributions: List[PatternContribution],
    ) -> Dict[str, float]:
        if not selected_entries:
            return {
                "consensus_score": 0.0,
                "immediate_score": 0.0,
                "negative_pressure": 1.0,
                "weighted_consensus": 0.0,
                "pattern_diversity": 0.0,
            }

        selected_numbers = [item[0] for item in selected_entries]
        positive_count = max(1, len(positive_contributions))

        # Consenso simples (quantidade de padrões)
        supporter_counts: List[int] = []
        for n in selected_numbers:
            supporters = 0
            for c in positive_contributions:
                if n in c.numbers:
                    supporters += 1
            supporter_counts.append(supporters)
        avg_supporters = (sum(supporter_counts) / len(supporter_counts)) if supporter_counts else 0.0
        consensus_score = max(0.0, min(1.0, avg_supporters / positive_count))

        # Consenso ponderado (considera peso dos padrões)
        total_weight = sum(c.weight for c in positive_contributions) or 1.0
        weighted_supporter_scores: List[float] = []
        for n in selected_numbers:
            weighted_support = 0.0
            for c in positive_contributions:
                if n in c.numbers:
                    weighted_support += c.weight
            weighted_supporter_scores.append(weighted_support / total_weight)
        weighted_consensus = (sum(weighted_supporter_scores) / len(weighted_supporter_scores)) if weighted_supporter_scores else 0.0

        # Diversidade de padrões (quantos tipos diferentes contribuíram)
        pattern_types = set()
        for c in positive_contributions:
            # Agrupar por tipo de padrão
            if "terminal" in c.pattern_id:
                pattern_types.add("terminal")
            elif "color" in c.pattern_id or "parity" in c.pattern_id:
                pattern_types.add("binary")
            elif "sector" in c.pattern_id or "transition" in c.pattern_id:
                pattern_types.add("sector")
            elif "dozen" in c.pattern_id or "column" in c.pattern_id:
                pattern_types.add("dozen_column")
            elif "robust" in c.pattern_id:
                pattern_types.add("multi_model")
            elif "hot" in c.pattern_id or "siege" in c.pattern_id:
                pattern_types.add("frequency")
            else:
                pattern_types.add("other")
        pattern_diversity = min(1.0, len(pattern_types) / 5.0)  # Normalizado por 5 tipos

        immediate_pattern_ids = {
            "terminal_repeat_sum_neighbors",
            "skipped_sequence_target_neighbors",
            "terminal_alternation_target_neighbors",
            "anchor_return_target_neighbors_mirrors",
        }
        immediate_active = len({c.pattern_id for c in positive_contributions if c.pattern_id in immediate_pattern_ids})
        immediate_score = max(0.0, min(1.0, immediate_active / len(immediate_pattern_ids)))

        total_positive = sum(item[2] for item in selected_entries)
        total_negative = sum(item[3] for item in selected_entries)
        neg_ratio = (total_negative / total_positive) if total_positive > 0 else 1.0
        negative_pressure = max(0.0, min(1.0, neg_ratio))

        return {
            "consensus_score": consensus_score,
            "immediate_score": immediate_score,
            "negative_pressure": negative_pressure,
            "weighted_consensus": weighted_consensus,
            "pattern_diversity": pattern_diversity,
        }

    @staticmethod
    def _rebalance_api_confidence(base_confidence: Dict[str, Any], context: Dict[str, float]) -> Dict[str, Any]:
        base_score = max(0, min(100, int(base_confidence.get("score", 0) or 0)))
        consensus_score = max(0.0, min(1.0, float(context.get("consensus_score", 0.0))))
        immediate_score = max(0.0, min(1.0, float(context.get("immediate_score", 0.0))))
        negative_pressure = max(0.0, min(1.0, float(context.get("negative_pressure", 0.0))))
        weighted_consensus = max(0.0, min(1.0, float(context.get("weighted_consensus", 0.0))))
        pattern_diversity = max(0.0, min(1.0, float(context.get("pattern_diversity", 0.0))))

        # Bonus por baixa pressão negativa
        weak_negative_bonus = max(0.0, (0.35 - negative_pressure) / 0.35) * 8.0 if negative_pressure < 0.35 else 0.0

        # Consenso simples
        consensus_boost = consensus_score * 10.0

        # Consenso ponderado (considera peso dos padrões) - mais importante
        weighted_consensus_boost = weighted_consensus * 14.0

        # Padrões imediatos
        immediate_boost = immediate_score * 8.0

        # Diversidade de tipos de padrão (evita depender de um único tipo)
        diversity_boost = pattern_diversity * 6.0

        # Penalidade por alta pressão negativa
        pressure_penalty = max(0.0, (negative_pressure - 0.55) / 0.45) * 16.0 if negative_pressure > 0.55 else 0.0

        adjusted = int(round(
            base_score
            + consensus_boost
            + weighted_consensus_boost
            + immediate_boost
            + diversity_boost
            + weak_negative_bonus
            - pressure_penalty
        ))
        adjusted = max(0, min(100, adjusted))

        if adjusted >= 75:
            label = "Alta"
        elif adjusted >= 50:
            label = "Media"
        else:
            label = "Baixa"
        return {"score": adjusted, "label": label}

    def _compute_adaptive_weights(
        self,
        definitions: List[PatternDefinition],
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
    ) -> tuple[Dict[str, float], List[Dict[str, Any]]]:
        if not definitions or len(history) < (from_index + 15):
            return ({}, [])

        signature = self._patterns_signature or self._build_patterns_signature()
        raw_history = ",".join(str(n) for n in history[from_index:])
        history_hash = hashlib.sha1(raw_history.encode("utf-8")).hexdigest()
        cache_key = f"{from_index}|{history_hash}|{hash(signature)}"
        cached = self._adaptive_weights_cache.get(cache_key)
        if cached is not None:
            return cached

        timeline = list(reversed(history[from_index:]))  # oldest -> newest
        multipliers: Dict[str, float] = {}
        details: List[Dict[str, Any]] = []

        for definition in definitions:
            cfg = definition.params.get("adaptive", {})
            if not isinstance(cfg, dict) or not bool(cfg.get("enabled", False)):
                continue
            if definition.kind != "positive":
                continue
            if definition.evaluator == "legacy_base_suggestion":
                continue

            evaluator = self._evaluator_registry.get(definition.evaluator)
            if evaluator is None:
                continue

            lookahead = max(1, int(cfg.get("lookahead", 3)))
            window = max(20, int(cfg.get("window", 180)))
            min_signals = max(1, int(cfg.get("min_signals", 12)))
            min_mult = float(cfg.get("min_multiplier", 0.8))
            max_mult = float(cfg.get("max_multiplier", 1.25))
            if min_mult > max_mult:
                min_mult, max_mult = max_mult, min_mult

            segment = timeline[-window:] if len(timeline) > window else timeline
            hits = 0
            signals = 0
            last_start = len(segment) - lookahead
            if last_start < 2:
                continue
            for cursor in range(2, last_start + 1):
                snapshot = list(reversed(segment[:cursor]))  # newest -> oldest (compat evaluator)
                try:
                    result = evaluator(snapshot, base_suggestion, 0, definition, None)
                except Exception:
                    continue
                numbers = {
                    self._normalize_number(n)
                    for n in result.get("numbers", [])
                    if self._is_valid_number(n)
                }
                if not numbers:
                    continue
                signals += 1
                future = segment[cursor : cursor + lookahead]
                if any(n in numbers for n in future):
                    hits += 1

            if signals <= 0:
                continue

            raw_rate = hits / signals
            sample_factor = min(1.0, signals / float(min_signals))
            adjusted_rate = 0.5 + ((raw_rate - 0.5) * sample_factor)
            multiplier = min_mult + (adjusted_rate * (max_mult - min_mult))
            multiplier = max(min_mult, min(max_mult, multiplier))

            multipliers[definition.id] = round(multiplier, 4)
            details.append(
                {
                    "pattern_id": definition.id,
                    "pattern_name": definition.name,
                    "signals": int(signals),
                    "hits": int(hits),
                    "hit_rate": round(raw_rate, 4),
                    "adjusted_rate": round(adjusted_rate, 4),
                    "multiplier": round(multiplier, 4),
                    "lookahead": int(lookahead),
                    "window": int(window),
                }
            )

        result = (multipliers, details)
        if len(self._adaptive_weights_cache) >= 16:
            first_key = next(iter(self._adaptive_weights_cache.keys()))
            self._adaptive_weights_cache.pop(first_key, None)
        self._adaptive_weights_cache[cache_key] = result
        return result

    def _load_patterns(self) -> List[PatternDefinition]:
        signature = self._build_patterns_signature()
        if self._patterns_signature is not None and signature == self._patterns_signature and self._patterns_cache:
            return list(self._patterns_cache)

        definitions: List[PatternDefinition] = []

        for path in sorted(self._patterns_dir.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Falha lendo pattern definition %s: %s", path, exc)
                continue

            try:
                definition = PatternDefinition(
                    id=str(raw["id"]),
                    name=str(raw.get("name", raw["id"])),
                    version=str(raw.get("version", "1.0.0")),
                    kind=str(raw.get("kind", "positive")).lower().strip() or "positive",
                    active=bool(raw.get("active", True)),
                    priority=int(raw.get("priority", 0)),
                    weight=float(raw.get("weight", 1.0)),
                    evaluator=str(raw["evaluator"]),
                    max_numbers=int(raw.get("max_numbers", 12)),
                    params=dict(raw.get("params", {})),
                )
            except Exception as exc:
                logger.warning("Pattern definition invalida em %s: %s", path, exc)
                continue

            if definition.active:
                definitions.append(definition)

        definitions.sort(key=lambda d: d.priority, reverse=True)
        self._patterns_signature = signature
        self._patterns_cache = list(definitions)
        return definitions

    def _build_patterns_signature(self) -> tuple[tuple[str, int, int], ...]:
        signature: List[tuple[str, int, int]] = []
        for path in sorted(self._patterns_dir.glob("*.json")):
            try:
                stat = path.stat()
                signature.append((path.name, int(stat.st_mtime_ns), int(stat.st_size)))
            except FileNotFoundError:
                continue
        return tuple(signature)

    @staticmethod
    def _is_valid_number(value: Any) -> bool:
        try:
            n = int(value)
        except (TypeError, ValueError):
            return False
        return 0 <= n <= 36

    @staticmethod
    def _normalize_number(value: Any) -> int:
        return int(value)

    @staticmethod
    def _sum_digits(n: int) -> int:
        return sum(int(ch) for ch in str(abs(int(n))))

    @staticmethod
    def _neighbors(num: int) -> List[int]:
        # Mantem compatibilidade com a regra que ja existe no front-end.
        if num == 26:
            return [3, 35]
        if num == 32:
            return [15, 19]

        if num not in WHEEL_ORDER:
            return []

        idx = WHEEL_ORDER.index(num)
        left = WHEEL_ORDER[(idx - 1 + len(WHEEL_ORDER)) % len(WHEEL_ORDER)]
        right = WHEEL_ORDER[(idx + 1) % len(WHEEL_ORDER)]
        return [left, right]

    @staticmethod
    def _neighbors_span(num: int, span: int = 2) -> List[int]:
        if span <= 0 or num not in WHEEL_ORDER:
            return []
        return [int(n) for n in get_wheel_neighbors(int(num), span=span)]

    @staticmethod
    def _mirror_numbers(num: int) -> List[int]:
        mirrors = get_mirror(int(num))
        return [int(n) for n in mirrors if 1 <= int(n) <= 36]

    def _eval_wheel_neighbors_5(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        del base_suggestion

        if from_index < 0 or from_index >= len(history):
            return {"numbers": [], "explanation": "Historico insuficiente para wheel_neighbors_5."}

        hist = [int(n) for n in history[from_index:] if self._is_valid_number(n)]
        if not hist:
            return {"numbers": [], "explanation": "Historico insuficiente para wheel_neighbors_5."}

        if focus_number is not None and self._is_valid_number(focus_number):
            base_number = int(focus_number)
        else:
            base_number = int(hist[0])

        params = dict(definition.params or {})
        feedback_storage_path = params.get("feedback_storage_path")
        requested_horizon = params.get("horizon_spins", params.get("default_horizon_spins", WHEEL_NEIGHBORS_5_DEFAULT_HORIZON))
        recent_window_size = max(1, int(params.get("recent_window_size", WHEEL_NEIGHBORS_5_RECENT_WINDOW)))
        feedback_anchor_size = max(4, int(params.get("feedback_anchor_size", WHEEL_NEIGHBORS_5_FEEDBACK_ANCHOR_SIZE)))

        resolved_feedback: List[Dict[str, Any]] = []
        feedback_store = get_wheel_neighbors_5_feedback_store(feedback_storage_path)
        if from_index == 0:
            resolved_feedback = feedback_store.resolve_from_history(
                history=[int(n) for n in history if self._is_valid_number(n)],
            )

        result = build_wheel_neighbors_5_result(
            base_number=base_number,
            requested_horizon=requested_horizon,
            recent_window_size=recent_window_size,
            base_weight=float(definition.weight or WHEEL_NEIGHBORS_5_BASE_WEIGHT),
            feedback_storage_path=feedback_storage_path,
            history=hist,
        )

        meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
        meta["feedback_mode"] = "global_live" if from_index == 0 else "disabled"
        if resolved_feedback:
            meta["resolved_feedback"] = resolved_feedback[:5]

        activation_candidates = [
            int(n)
            for n in meta.get("ordered_candidates", result.get("numbers", []))
            if self._is_valid_number(n)
        ]
        if from_index == 0 and activation_candidates:
            horizon_meta = meta.get("horizon_config_used", {}) if isinstance(meta.get("horizon_config_used"), dict) else {}
            activation = feedback_store.register_activation(
                base_number=base_number,
                ordered_candidates=activation_candidates,
                candidate_positions=meta.get("candidate_positions", {}),
                horizon_used=resolve_wheel_neighbors_5_horizon(
                    horizon_meta.get("horizon_used", requested_horizon)
                ),
                expected_hit_rate=float(
                    horizon_meta.get("expected_hit_rate", 0.0)
                ),
                history_anchor=[int(n) for n in history[:feedback_anchor_size] if self._is_valid_number(n)],
                recent_snapshot=meta.get("recent_performance_snapshot", {}),
            )
            if activation:
                meta["feedback_activation"] = {
                    "activation_id": activation.get("activation_id"),
                    "status": activation.get("status"),
                    "created_at": activation.get("created_at"),
                }

        result["meta"] = meta
        return result

    def _exact_repeat_delayed_counts_and_targets(self, repeated_number: int) -> tuple[List[int], List[int]]:
        repeated_number = int(repeated_number)
        if repeated_number in {11, 22, 33}:
            target_bases = [11, 22, 33]
        else:
            target_bases = sorted({repeated_number, *self._mirror_numbers(repeated_number)})
        count_values = sorted({n for n in target_bases if 1 <= int(n) <= 36})
        return count_values, target_bases

    def _build_exact_repeat_target_cluster(
        self,
        target_bases: List[int],
        base_score: float,
        near_neighbor_score: float,
        far_neighbor_score: float,
        zero_score: float,
    ) -> Dict[int, float]:
        scores: Dict[int, float] = {}

        for base in target_bases:
            scores[int(base)] = max(float(scores.get(int(base), 0.0)), float(base_score))
            neighbors = self._neighbors_span(int(base), span=2)
            for idx, neighbor in enumerate(neighbors):
                score = near_neighbor_score if idx in (1, 2) else far_neighbor_score
                scores[int(neighbor)] = max(float(scores.get(int(neighbor), 0.0)), float(score))

        scores[0] = max(float(scores.get(0, 0.0)), float(zero_score))
        return scores

    @staticmethod
    def _wheel_neighbor_step(first: int, second: int) -> int | None:
        if first not in WHEEL_ORDER or second not in WHEEL_ORDER:
            return None

        idx_first = WHEEL_ORDER.index(int(first))
        idx_second = WHEEL_ORDER.index(int(second))
        if idx_second == ((idx_first + 1) % len(WHEEL_ORDER)):
            return 1
        if idx_second == ((idx_first - 1) % len(WHEEL_ORDER)):
            return -1
        return None

    def _build_neighbor_repeat_target_cluster(
        self,
        first: int,
        second: int,
        pair_score: float,
        near_neighbor_score: float,
        far_neighbor_score: float,
        zero_score: float,
    ) -> tuple[List[int], Dict[int, float]]:
        step = self._wheel_neighbor_step(int(first), int(second))
        if step is None:
            return ([], {})

        idx_first = WHEEL_ORDER.index(int(first))
        idx_second = WHEEL_ORDER.index(int(second))
        away_step = -step

        cluster_order = [
            WHEEL_ORDER[(idx_first + (2 * away_step)) % len(WHEEL_ORDER)],
            WHEEL_ORDER[(idx_first + away_step) % len(WHEEL_ORDER)],
            int(first),
            int(second),
            WHEEL_ORDER[(idx_second + step) % len(WHEEL_ORDER)],
            WHEEL_ORDER[(idx_second + (2 * step)) % len(WHEEL_ORDER)],
            0,
        ]
        cluster_scores = {
            int(cluster_order[0]): float(far_neighbor_score),
            int(cluster_order[1]): float(near_neighbor_score),
            int(cluster_order[2]): float(pair_score),
            int(cluster_order[3]): float(pair_score),
            int(cluster_order[4]): float(near_neighbor_score),
            int(cluster_order[5]): float(far_neighbor_score),
            0: float(zero_score),
        }
        return (cluster_order, cluster_scores)

    def _numbers_with_same_terminal(self, base_number: int) -> List[int]:
        terminal = int(base_number) % 10
        return [
            n
            for n in range(1, 37)
            if (n % 10) == terminal and int(n) != int(base_number)
        ]

    def _build_terminal_repeat_sum_target_cluster(
        self,
        target_number: int,
        target_score: float,
        near_neighbor_score: float,
        far_neighbor_score: float,
        terminal_score: float,
        zero_score: float,
    ) -> tuple[List[int], Dict[int, float]]:
        target_number = int(target_number)
        if target_number not in WHEEL_ORDER:
            return ([], {})

        neighbors = self._neighbors_span(target_number, span=2)
        if len(neighbors) != 4:
            return ([], {})

        cluster_order = [
            int(neighbors[0]),
            int(neighbors[1]),
            int(target_number),
            int(neighbors[2]),
            int(neighbors[3]),
        ]
        scores: Dict[int, float] = {
            int(neighbors[0]): float(far_neighbor_score),
            int(neighbors[1]): float(near_neighbor_score),
            int(target_number): float(target_score),
            int(neighbors[2]): float(near_neighbor_score),
            int(neighbors[3]): float(far_neighbor_score),
        }

        for terminal_number in self._numbers_with_same_terminal(target_number):
            if terminal_number not in scores:
                cluster_order.append(int(terminal_number))
            scores[int(terminal_number)] = max(float(scores.get(int(terminal_number), 0.0)), float(terminal_score))

        if 0 not in scores:
            cluster_order.append(0)
        scores[0] = max(float(scores.get(0, 0.0)), float(zero_score))
        return (cluster_order, scores)

    def _build_repeat_trend_projection_target_cluster(
        self,
        base_number: int,
        target_score: float,
        neighbor_score: float,
        zero_score: float,
    ) -> tuple[List[int], Dict[int, float]]:
        cluster_order: List[int] = []
        scores: Dict[int, float] = {}
        seen: Set[int] = set()

        for projected in (int(base_number) - 1, int(base_number) + 1):
            if not (1 <= projected <= 36):
                continue
            neighbors = self._neighbors(projected)
            if len(neighbors) == 2:
                for n in (int(neighbors[0]), projected, int(neighbors[1])):
                    if n not in seen:
                        cluster_order.append(int(n))
                        seen.add(int(n))
                scores[int(neighbors[0])] = max(float(scores.get(int(neighbors[0]), 0.0)), float(neighbor_score))
                scores[int(projected)] = max(float(scores.get(int(projected), 0.0)), float(target_score))
                scores[int(neighbors[1])] = max(float(scores.get(int(neighbors[1]), 0.0)), float(neighbor_score))
            else:
                if projected not in seen:
                    cluster_order.append(int(projected))
                    seen.add(int(projected))
                scores[int(projected)] = max(float(scores.get(int(projected), 0.0)), float(target_score))

        if 0 not in seen:
            cluster_order.append(0)
        scores[0] = max(float(scores.get(0, 0.0)), float(zero_score))
        return (cluster_order, scores)

    def _build_middle_trend_projection_target_cluster(
        self,
        base_numbers: List[int],
        target_score: float,
        neighbor_score: float,
        zero_score: float,
    ) -> tuple[List[int], Dict[int, float]]:
        cluster_order: List[int] = []
        scores: Dict[int, float] = {}
        seen: Set[int] = set()

        for base_number in base_numbers:
            for projected in (int(base_number) - 1, int(base_number) + 1):
                if not (1 <= projected <= 36):
                    continue
                neighbors = self._neighbors(projected)
                if len(neighbors) == 2:
                    for n in (int(neighbors[0]), projected, int(neighbors[1])):
                        if n not in seen:
                            cluster_order.append(int(n))
                            seen.add(int(n))
                    scores[int(neighbors[0])] = max(float(scores.get(int(neighbors[0]), 0.0)), float(neighbor_score))
                    scores[int(projected)] = max(float(scores.get(int(projected), 0.0)), float(target_score))
                    scores[int(neighbors[1])] = max(float(scores.get(int(neighbors[1]), 0.0)), float(neighbor_score))
                else:
                    if projected not in seen:
                        cluster_order.append(int(projected))
                        seen.add(int(projected))
                    scores[int(projected)] = max(float(scores.get(int(projected), 0.0)), float(target_score))

        if 0 not in seen:
            cluster_order.append(0)
        scores[0] = max(float(scores.get(0, 0.0)), float(zero_score))
        return (cluster_order, scores)

    def _build_exact_alternation_target_cluster(
        self,
        target_bases: List[int],
        base_score: float,
        near_neighbor_score: float,
        far_neighbor_score: float,
        zero_score: float,
    ) -> tuple[List[int], Dict[int, float]]:
        cluster_order: List[int] = []
        scores: Dict[int, float] = {}
        seen: Set[int] = set()

        for base in target_bases:
            neighbors = self._neighbors_span(int(base), span=2)
            if len(neighbors) != 4:
                continue

            ordered_group = [
                int(neighbors[3]),
                int(neighbors[2]),
                int(base),
                int(neighbors[1]),
                int(neighbors[0]),
            ]
            for number in ordered_group:
                if number not in seen:
                    cluster_order.append(int(number))
                    seen.add(int(number))

            scores[int(neighbors[0])] = max(float(scores.get(int(neighbors[0]), 0.0)), float(far_neighbor_score))
            scores[int(neighbors[1])] = max(float(scores.get(int(neighbors[1]), 0.0)), float(near_neighbor_score))
            scores[int(base)] = max(float(scores.get(int(base), 0.0)), float(base_score))
            scores[int(neighbors[2])] = max(float(scores.get(int(neighbors[2]), 0.0)), float(near_neighbor_score))
            scores[int(neighbors[3])] = max(float(scores.get(int(neighbors[3]), 0.0)), float(far_neighbor_score))

        if 0 not in seen:
            cluster_order.append(0)
        scores[0] = max(float(scores.get(0, 0.0)), float(zero_score))
        return (cluster_order, scores)

    def _color_neighbor_missing_number(self, first: int, second: int) -> int | None:
        first = int(first)
        second = int(second)
        if first == 0 or second == 0:
            return None

        first_is_red = first in RED_NUMBERS
        second_is_red = second in RED_NUMBERS
        first_is_black = first in BLACK_NUMBERS
        second_is_black = second in BLACK_NUMBERS
        if not ((first_is_red and second_is_red) or (first_is_black and second_is_black)):
            return None

        if first not in WHEEL_ORDER or second not in WHEEL_ORDER:
            return None

        idx_first = WHEEL_ORDER.index(first)
        idx_second = WHEEL_ORDER.index(second)
        wheel_len = len(WHEEL_ORDER)

        if idx_second == ((idx_first + 2) % wheel_len):
            return int(WHEEL_ORDER[(idx_first + 1) % wheel_len])
        if idx_second == ((idx_first - 2) % wheel_len):
            return int(WHEEL_ORDER[(idx_first - 1) % wheel_len])
        return None

    def _build_color_neighbor_missing_target_cluster(
        self,
        target_bases: List[int],
        base_score: float,
        near_neighbor_score: float,
        far_neighbor_score: float,
        zero_score: float,
    ) -> tuple[List[int], Dict[int, float]]:
        cluster_order: List[int] = []
        scores: Dict[int, float] = {}
        seen: Set[int] = set()

        for base in target_bases:
            neighbors = self._neighbors_span(int(base), span=2)
            if len(neighbors) != 4:
                continue

            ordered_group = [
                int(neighbors[0]),
                int(neighbors[1]),
                int(base),
                int(neighbors[2]),
                int(neighbors[3]),
            ]
            for number in ordered_group:
                if number not in seen:
                    cluster_order.append(int(number))
                    seen.add(int(number))

            scores[int(neighbors[0])] = max(float(scores.get(int(neighbors[0]), 0.0)), float(far_neighbor_score))
            scores[int(neighbors[1])] = max(float(scores.get(int(neighbors[1]), 0.0)), float(near_neighbor_score))
            scores[int(base)] = max(float(scores.get(int(base), 0.0)), float(base_score))
            scores[int(neighbors[2])] = max(float(scores.get(int(neighbors[2]), 0.0)), float(near_neighbor_score))
            scores[int(neighbors[3])] = max(float(scores.get(int(neighbors[3]), 0.0)), float(far_neighbor_score))

        if 0 not in seen:
            cluster_order.append(0)
        scores[0] = max(float(scores.get(0, 0.0)), float(zero_score))
        return (cluster_order, scores)

    def _build_terminal_middle_entry_target_cluster(
        self,
        target_number: int,
        target_score: float,
        near_neighbor_score: float,
        mid_neighbor_score: float,
        far_neighbor_score: float,
        zero_score: float,
        span: int = 3,
    ) -> tuple[List[int], Dict[int, float]]:
        target_number = int(target_number)
        neighbors = self._neighbors_span(target_number, span=span)
        if len(neighbors) != span * 2:
            return ([], {})

        left = [int(n) for n in neighbors[:span]]
        right = [int(n) for n in neighbors[span:]]
        cluster_order = [*left, int(target_number), *right, 0]
        scores: Dict[int, float] = {int(target_number): float(target_score), 0: float(zero_score)}

        if span >= 3:
            level_scores = [float(far_neighbor_score), float(mid_neighbor_score), float(near_neighbor_score)]
            for idx, number in enumerate(left):
                scores[int(number)] = max(float(scores.get(int(number), 0.0)), level_scores[idx])
            for idx, number in enumerate(right):
                reverse_idx = (span - 1) - idx
                scores[int(number)] = max(float(scores.get(int(number), 0.0)), level_scores[reverse_idx])
        else:
            for number in left + right:
                scores[int(number)] = max(float(scores.get(int(number), 0.0)), float(near_neighbor_score))

        return (cluster_order, scores)

    def _eval_neighbor_repeat_delayed_entry(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        hist = [int(n) for n in history[from_index:] if self._is_valid_number(n)]
        if len(hist) < 3:
            return {"numbers": [], "explanation": "Historico insuficiente para dupla colada com entrada atrasada."}

        timeline = list(reversed(hist))  # oldest -> newest
        current_idx = len(timeline) - 1

        attempts = max(1, int(definition.params.get("attempts_per_count", 5)))
        cancel_lookback = max(1, int(definition.params.get("cancel_lookback", 4)))
        pair_score = float(definition.params.get("pair_score", 1.0))
        near_neighbor_score = float(definition.params.get("near_neighbor_score", 0.9))
        far_neighbor_score = float(definition.params.get("far_neighbor_score", 0.75))
        zero_score = float(definition.params.get("zero_score", 0.7))

        active_signals: List[Dict[str, Any]] = []
        pending_items: List[Dict[str, Any]] = []
        cancelled_items: List[Dict[str, Any]] = []
        recent_window = [int(n) for n in hist[:cancel_lookback]]

        for pair_end in range(1, len(timeline)):
            first = int(timeline[pair_end - 1])
            second = int(timeline[pair_end])
            if first == 0 or second == 0:
                continue

            cluster_order, cluster_scores = self._build_neighbor_repeat_target_cluster(
                first=first,
                second=second,
                pair_score=pair_score,
                near_neighbor_score=near_neighbor_score,
                far_neighbor_score=far_neighbor_score,
                zero_score=zero_score,
            )
            if not cluster_order:
                continue

            base_count = max(first, second)
            window_start = int(base_count)
            window_end = int(base_count + attempts - 1)
            target_set = set(cluster_order)
            completed_spins_since_trigger = current_idx - pair_end
            next_round_number = completed_spins_since_trigger + 1
            window_indices = [pair_end + offset for offset in range(window_start, window_end + 1)]
            observed_indices = [idx for idx in window_indices if idx <= current_idx]

            if any(int(timeline[idx]) in target_set for idx in observed_indices):
                continue

            if next_round_number < window_start:
                pending_items.append(
                    {
                        "pair": [int(first), int(second)],
                        "base_count": int(base_count),
                        "remaining": int(window_start - next_round_number),
                        "spins_since_trigger": int(completed_spins_since_trigger),
                        "cluster_order": list(cluster_order),
                    }
                )
                continue

            if next_round_number > window_end:
                continue

            if any(number in target_set for number in recent_window):
                cancelled_items.append(
                    {
                        "pair": [int(first), int(second)],
                        "base_count": int(base_count),
                        "recent_window": list(recent_window),
                        "cluster_order": list(cluster_order),
                    }
                )
                continue

            active_signals.append(
                {
                    "pair": [int(first), int(second)],
                    "base_count": int(base_count),
                    "attempt": int((next_round_number - window_start) + 1),
                    "window_start": int(window_start),
                    "window_end": int(window_end),
                    "numbers": list(cluster_order),
                    "scores": dict(cluster_scores),
                    "spins_since_trigger": int(completed_spins_since_trigger),
                    "explanation": (
                        f"Dupla colada na race {first}-{second} ativa. "
                        f"Contagem base {base_count} com janela {window_start}-{window_end} "
                        f"(tentativa {(next_round_number - window_start) + 1}/{attempts})."
                    ),
                }
            )

        if not active_signals:
            if cancelled_items:
                return {
                    "numbers": [],
                    "explanation": "Entrada anulada: alvo da dupla apareceu nos 4 ultimos spins antes da entrada.",
                    "pending_items": pending_items,
                    "meta": {
                        "cancelled_signals": cancelled_items,
                        "recent_window": recent_window,
                    },
                }
            if pending_items:
                min_remaining = min(int(item["remaining"]) for item in pending_items)
                return {
                    "numbers": [],
                    "explanation": f"Padrao em monitoramento. Aguardando {min_remaining} giro(s) para a janela da dupla.",
                    "pending_items": pending_items,
                    "meta": {
                        "recent_window": recent_window,
                    },
                }
            return {
                "numbers": [],
                "explanation": "Nenhuma dupla colada na race com janela atrasada ativa no momento.",
                "pending_items": [],
                "meta": {
                    "recent_window": recent_window,
                },
            }

        split_contributions: List[Dict[str, Any]] = []
        aggregate_scores: Dict[int, float] = defaultdict(float)
        ordered_numbers: List[int] = []
        seen_numbers: Set[int] = set()

        for index, signal in enumerate(active_signals, start=1):
            for number in signal["numbers"]:
                if number not in seen_numbers:
                    ordered_numbers.append(int(number))
                    seen_numbers.add(int(number))
            for number, score in signal["scores"].items():
                aggregate_scores[int(number)] += float(score)

            split_contributions.append(
                {
                    "pattern_id": f"{definition.id}_{signal['pair'][0]}_{signal['pair'][1]}_{signal['base_count']}_{index}",
                    "pattern_name": f"{definition.name} [{signal['pair'][0]}-{signal['pair'][1]}]",
                    "numbers": list(signal["numbers"]),
                    "scores": dict(signal["scores"]),
                    "weight": float(definition.weight),
                    "explanation": str(signal["explanation"]),
                }
            )

        final_scores = {int(n): float(aggregate_scores[n]) for n in ordered_numbers}
        active_windows = ", ".join(
            f"{signal['pair'][0]}-{signal['pair'][1]}:{signal['window_start']}-{signal['window_end']}"
            for signal in active_signals
        )
        return {
            "numbers": ordered_numbers,
            "scores": final_scores,
            "split_contributions": split_contributions,
            "pending_items": pending_items,
            "explanation": (
                f"Dupla colada na race ativa em {len(active_signals)} sinal(is). Janela(s): {active_windows}."
            ),
            "meta": {
                "active_signals": active_signals,
                "cancelled_signals": cancelled_items,
                "recent_window": recent_window,
            },
        }

    def _eval_terminal_repeat_sum_delayed_entry(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        hist = [int(n) for n in history[from_index:] if self._is_valid_number(n)]
        if len(hist) < 3:
            return {"numbers": [], "explanation": "Historico insuficiente para repeticao terminal com soma atrasada."}

        timeline = list(reversed(hist))  # oldest -> newest
        current_idx = len(timeline) - 1

        wait_spins = max(0, int(definition.params.get("wait_spins", 4)))
        attempts = max(1, int(definition.params.get("attempts_per_count", 5)))
        cancel_lookback = max(1, int(definition.params.get("cancel_lookback", 4)))
        target_score = float(definition.params.get("target_score", 1.0))
        near_neighbor_score = float(definition.params.get("near_neighbor_score", 0.9))
        far_neighbor_score = float(definition.params.get("far_neighbor_score", 0.75))
        terminal_score = float(definition.params.get("terminal_score", 0.8))
        zero_score = float(definition.params.get("zero_score", 0.7))

        active_signals: List[Dict[str, Any]] = []
        pending_items: List[Dict[str, Any]] = []
        cancelled_items: List[Dict[str, Any]] = []
        recent_window = [int(n) for n in hist[:cancel_lookback]]

        for pair_end in range(1, len(timeline)):
            first = int(timeline[pair_end - 1])  # mais antigo da dupla
            second = int(timeline[pair_end])     # mais recente da dupla
            if first == 0 or second == 0:
                continue
            if first == second:
                continue
            if (first % 10) != (second % 10):
                continue

            sum_target = self._sum_digits(first)
            cluster_order, cluster_scores = self._build_terminal_repeat_sum_target_cluster(
                target_number=sum_target,
                target_score=target_score,
                near_neighbor_score=near_neighbor_score,
                far_neighbor_score=far_neighbor_score,
                terminal_score=terminal_score,
                zero_score=zero_score,
            )
            if not cluster_order:
                continue

            target_set = set(cluster_scores.keys())
            completed_spins_since_trigger = current_idx - pair_end
            next_round_number = completed_spins_since_trigger + 1
            wait_indices = [pair_end + offset for offset in range(1, wait_spins + 1)]
            observed_wait_indices = [idx for idx in wait_indices if idx <= current_idx]

            if any(int(timeline[idx]) in target_set for idx in observed_wait_indices):
                cancelled_items.append(
                    {
                        "pair": [int(first), int(second)],
                        "sum_target": int(sum_target),
                        "recent_wait_numbers": [int(timeline[idx]) for idx in observed_wait_indices],
                        "cluster_order": list(cluster_order),
                    }
                )
                continue

            window_start = int(wait_spins + 1)
            window_end = int(wait_spins + attempts)
            entry_indices = [pair_end + offset for offset in range(window_start, window_end + 1)]
            observed_entry_indices = [idx for idx in entry_indices if idx <= current_idx]

            if any(int(timeline[idx]) in target_set for idx in observed_entry_indices):
                continue

            if next_round_number < window_start:
                pending_items.append(
                    {
                        "pair": [int(first), int(second)],
                        "sum_target": int(sum_target),
                        "remaining": int(window_start - next_round_number),
                        "spins_since_trigger": int(completed_spins_since_trigger),
                    }
                )
                continue

            if next_round_number > window_end:
                continue

            if any(number in target_set for number in recent_window):
                cancelled_items.append(
                    {
                        "pair": [int(first), int(second)],
                        "sum_target": int(sum_target),
                        "recent_window": list(recent_window),
                        "cluster_order": list(cluster_order),
                    }
                )
                continue

            active_signals.append(
                {
                    "pair": [int(first), int(second)],
                    "sum_target": int(sum_target),
                    "window_start": int(window_start),
                    "window_end": int(window_end),
                    "attempt": int((next_round_number - window_start) + 1),
                    "numbers": list(cluster_order),
                    "scores": dict(cluster_scores),
                    "spins_since_trigger": int(completed_spins_since_trigger),
                    "explanation": (
                        f"Repeticao de terminal {first}-{second} ativa. "
                        f"Soma do primeiro numero ({first}) = {sum_target}. "
                        f"Espera fixa {wait_spins} e janela {window_start}-{window_end} "
                        f"(tentativa {(next_round_number - window_start) + 1}/{attempts})."
                    ),
                }
            )

        if not active_signals:
            if cancelled_items:
                return {
                    "numbers": [],
                    "explanation": "Entrada anulada: alvo apareceu durante a espera ou nos 4 ultimos spins antes da entrada.",
                    "pending_items": pending_items,
                    "meta": {
                        "cancelled_signals": cancelled_items,
                        "recent_window": recent_window,
                        "future_extension_note": "Caso ampliado 6/9 permanece desativado nesta versao.",
                    },
                }
            if pending_items:
                min_remaining = min(int(item["remaining"]) for item in pending_items)
                return {
                    "numbers": [],
                    "explanation": f"Padrao em monitoramento. Aguardando {min_remaining} giro(s) para abrir a janela de entrada.",
                    "pending_items": pending_items,
                    "meta": {
                        "recent_window": recent_window,
                        "future_extension_note": "Caso ampliado 6/9 permanece desativado nesta versao.",
                    },
                }
            return {
                "numbers": [],
                "explanation": "Nenhuma repeticao de terminal com soma atrasada ativa no momento.",
                "pending_items": [],
                "meta": {
                    "recent_window": recent_window,
                    "future_extension_note": "Caso ampliado 6/9 permanece desativado nesta versao.",
                },
            }

        split_contributions: List[Dict[str, Any]] = []
        aggregate_scores: Dict[int, float] = defaultdict(float)
        ordered_numbers: List[int] = []
        seen_numbers: Set[int] = set()

        for index, signal in enumerate(active_signals, start=1):
            for number in signal["numbers"]:
                if int(number) in seen_numbers:
                    continue
                seen_numbers.add(int(number))
                ordered_numbers.append(int(number))
            for number, score in signal["scores"].items():
                aggregate_scores[int(number)] += float(score)

            split_contributions.append(
                {
                    "pattern_id": f"{definition.id}_{signal['pair'][0]}_{signal['pair'][1]}_{signal['sum_target']}_{index}",
                    "pattern_name": f"{definition.name} [{signal['pair'][0]}-{signal['pair'][1]}]",
                    "numbers": list(signal["numbers"]),
                    "scores": dict(signal["scores"]),
                    "weight": float(definition.weight),
                    "explanation": str(signal["explanation"]),
                }
            )

        final_scores = {int(n): float(aggregate_scores[n]) for n in ordered_numbers}
        active_windows = ", ".join(
            f"{signal['pair'][0]}-{signal['pair'][1]}:{signal['window_start']}-{signal['window_end']}"
            for signal in active_signals
        )
        return {
            "numbers": ordered_numbers,
            "scores": final_scores,
            "split_contributions": split_contributions,
            "pending_items": pending_items,
            "explanation": (
                f"Repeticao de terminal com soma atrasada ativa em {len(active_signals)} sinal(is). Janela(s): {active_windows}."
            ),
            "meta": {
                "active_signals": active_signals,
                "cancelled_signals": cancelled_items,
                "recent_window": recent_window,
                "future_extension_note": "Caso ampliado 6/9 permanece desativado nesta versao.",
            },
        }

    def _eval_repeat_trend_next_projection_delayed_entry(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        hist = [int(n) for n in history[from_index:] if self._is_valid_number(n)]
        if len(hist) < 3:
            return {"numbers": [], "explanation": "Historico insuficiente para projecao de tendencia com entrada atrasada."}

        timeline = list(reversed(hist))  # oldest -> newest
        current_idx = len(timeline) - 1

        wait_spins = max(0, int(definition.params.get("wait_spins", 4)))
        attempts = max(1, int(definition.params.get("attempts_per_count", 5)))
        target_score = float(definition.params.get("target_score", 1.0))
        neighbor_score = float(definition.params.get("neighbor_score", 0.85))
        zero_score = float(definition.params.get("zero_score", 0.7))

        active_signals: List[Dict[str, Any]] = []
        pending_items: List[Dict[str, Any]] = []
        cancelled_items: List[Dict[str, Any]] = []

        for base_idx in range(2, len(timeline)):
            first = int(timeline[base_idx - 2])
            second = int(timeline[base_idx - 1])
            base_number = int(timeline[base_idx])

            if first == 0 or second == 0:
                continue

            delta = second - first
            if delta not in {1, -1}:
                continue

            cluster_order, cluster_scores = self._build_repeat_trend_projection_target_cluster(
                base_number=base_number,
                target_score=target_score,
                neighbor_score=neighbor_score,
                zero_score=zero_score,
            )
            if not cluster_order:
                continue

            target_set = set(cluster_scores.keys())
            completed_spins_since_base = current_idx - base_idx
            next_round_number = completed_spins_since_base + 1

            wait_indices = [base_idx + offset for offset in range(1, wait_spins + 1)]
            observed_wait_indices = [idx for idx in wait_indices if idx <= current_idx]
            if any(int(timeline[idx]) in target_set for idx in observed_wait_indices):
                cancelled_items.append(
                    {
                        "trend_pair": [int(first), int(second)],
                        "base_number": int(base_number),
                        "direction": "up" if delta > 0 else "down",
                        "recent_wait_numbers": [int(timeline[idx]) for idx in observed_wait_indices],
                        "cluster_order": list(cluster_order),
                    }
                )
                continue

            window_start = int(wait_spins + 1)
            window_end = int(wait_spins + attempts)
            entry_indices = [base_idx + offset for offset in range(window_start, window_end + 1)]
            observed_entry_indices = [idx for idx in entry_indices if idx <= current_idx]
            if any(int(timeline[idx]) in target_set for idx in observed_entry_indices):
                continue

            if next_round_number < window_start:
                pending_items.append(
                    {
                        "trend_pair": [int(first), int(second)],
                        "base_number": int(base_number),
                        "direction": "up" if delta > 0 else "down",
                        "remaining": int(window_start - next_round_number),
                        "spins_since_base": int(completed_spins_since_base),
                    }
                )
                continue

            if next_round_number > window_end:
                continue

            active_signals.append(
                {
                    "trend_pair": [int(first), int(second)],
                    "base_number": int(base_number),
                    "direction": "up" if delta > 0 else "down",
                    "window_start": int(window_start),
                    "window_end": int(window_end),
                    "attempt": int((next_round_number - window_start) + 1),
                    "numbers": list(cluster_order),
                    "scores": dict(cluster_scores),
                    "spins_since_base": int(completed_spins_since_base),
                    "explanation": (
                        f"Tendencia {'crescente' if delta > 0 else 'decrescente'} {first}->{second} ativa. "
                        f"Base seguinte {base_number}. Espera fixa {wait_spins} e janela {window_start}-{window_end} "
                        f"(tentativa {(next_round_number - window_start) + 1}/{attempts})."
                    ),
                }
            )

        if not active_signals:
            if cancelled_items:
                return {
                    "numbers": [],
                    "explanation": "Entrada anulada: alvo apareceu nas 4 rodadas de espera.",
                    "pending_items": pending_items,
                    "meta": {
                        "cancelled_signals": cancelled_items,
                    },
                }
            if pending_items:
                min_remaining = min(int(item["remaining"]) for item in pending_items)
                return {
                    "numbers": [],
                    "explanation": f"Padrao em monitoramento. Aguardando {min_remaining} giro(s) para abrir a janela de entrada.",
                    "pending_items": pending_items,
                    "meta": {},
                }
            return {
                "numbers": [],
                "explanation": "Nenhuma projecao de tendencia com entrada atrasada ativa no momento.",
                "pending_items": [],
                "meta": {},
            }

        split_contributions: List[Dict[str, Any]] = []
        aggregate_scores: Dict[int, float] = defaultdict(float)
        ordered_numbers: List[int] = []
        seen_numbers: Set[int] = set()

        for index, signal in enumerate(active_signals, start=1):
            for number in signal["numbers"]:
                if int(number) in seen_numbers:
                    continue
                seen_numbers.add(int(number))
                ordered_numbers.append(int(number))
            for number, score in signal["scores"].items():
                aggregate_scores[int(number)] += float(score)

            split_contributions.append(
                {
                    "pattern_id": f"{definition.id}_{signal['trend_pair'][0]}_{signal['trend_pair'][1]}_{signal['base_number']}_{index}",
                    "pattern_name": f"{definition.name} [{signal['trend_pair'][0]}-{signal['trend_pair'][1]}->{signal['base_number']}]",
                    "numbers": list(signal["numbers"]),
                    "scores": dict(signal["scores"]),
                    "weight": float(definition.weight),
                    "explanation": str(signal["explanation"]),
                }
            )

        final_scores = {int(n): float(aggregate_scores[n]) for n in ordered_numbers}
        active_windows = ", ".join(
            f"{signal['trend_pair'][0]}-{signal['trend_pair'][1]}->{signal['base_number']}:{signal['window_start']}-{signal['window_end']}"
            for signal in active_signals
        )
        return {
            "numbers": ordered_numbers,
            "scores": final_scores,
            "split_contributions": split_contributions,
            "pending_items": pending_items,
            "explanation": (
                f"Projecao de tendencia com entrada atrasada ativa em {len(active_signals)} sinal(is). Janela(s): {active_windows}."
            ),
            "meta": {
                "active_signals": active_signals,
                "cancelled_signals": cancelled_items,
            },
        }

    def _eval_exact_alternation_delayed_entry(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        hist = [int(n) for n in history[from_index:] if self._is_valid_number(n)]
        if len(hist) < 3:
            return {"numbers": [], "explanation": "Historico insuficiente para alternancia exata com entrada atrasada."}

        timeline = list(reversed(hist))  # oldest -> newest
        current_idx = len(timeline) - 1

        attempts = max(1, int(definition.params.get("attempts_per_count", 6)))
        cancel_lookback = max(1, int(definition.params.get("cancel_lookback", 4)))
        base_score = float(definition.params.get("base_score", 1.0))
        near_neighbor_score = float(definition.params.get("near_neighbor_score", 0.9))
        far_neighbor_score = float(definition.params.get("far_neighbor_score", 0.75))
        zero_score = float(definition.params.get("zero_score", 0.7))

        active_signals: List[Dict[str, Any]] = []
        pending_items: List[Dict[str, Any]] = []
        cancelled_items: List[Dict[str, Any]] = []

        for pattern_end in range(2, len(timeline)):
            first_a = int(timeline[pattern_end - 2])
            middle_b = int(timeline[pattern_end - 1])
            last_a = int(timeline[pattern_end])

            if first_a == 0 or middle_b == 0 or last_a == 0:
                continue
            if first_a != last_a:
                continue
            if middle_b == first_a:
                continue

            count_values, target_bases = self._exact_repeat_delayed_counts_and_targets(middle_b)
            if not count_values or not target_bases:
                continue

            cluster_order, cluster_scores = self._build_exact_alternation_target_cluster(
                target_bases=target_bases,
                base_score=base_score,
                near_neighbor_score=near_neighbor_score,
                far_neighbor_score=far_neighbor_score,
                zero_score=zero_score,
            )
            if not cluster_order:
                continue

            target_set = set(cluster_scores.keys())
            completed_spins_since_trigger = current_idx - pattern_end
            next_round_number = completed_spins_since_trigger + 1
            first_count = int(min(count_values))

            if next_round_number >= first_count:
                cancel_start = max(1, first_count - cancel_lookback)
                cancel_indices = [pattern_end + offset for offset in range(cancel_start, first_count)]
                observed_cancel_indices = [idx for idx in cancel_indices if idx <= current_idx]
                if any(int(timeline[idx]) in target_set for idx in observed_cancel_indices):
                    cancelled_items.append(
                        {
                            "formation": [int(first_a), int(middle_b), int(last_a)],
                            "target_bases": list(target_bases),
                            "count_values": list(count_values),
                            "cluster_order": list(cluster_order),
                        }
                    )
                    continue

            matched_window: Dict[str, Any] | None = None
            blocked_by_hit = False

            for count_value in count_values:
                window_start = int(count_value)
                window_end = int(count_value + attempts - 1)
                window_indices = [pattern_end + offset for offset in range(window_start, window_end + 1)]
                observed_window_indices = [idx for idx in window_indices if idx <= current_idx]

                if any(int(timeline[idx]) in target_set for idx in observed_window_indices):
                    blocked_by_hit = True
                    break

                if next_round_number < window_start:
                    pending_items.append(
                        {
                            "formation": [int(first_a), int(middle_b), int(last_a)],
                            "target_bases": list(target_bases),
                            "count_values": list(count_values),
                            "next_count": int(window_start),
                            "remaining": int(window_start - next_round_number),
                            "spins_since_trigger": int(completed_spins_since_trigger),
                        }
                    )
                    break

                if window_start <= next_round_number <= window_end:
                    matched_window = {
                        "window_start": int(window_start),
                        "window_end": int(window_end),
                        "attempt": int((next_round_number - window_start) + 1),
                    }
                    break

            if blocked_by_hit or matched_window is None:
                continue

            active_signals.append(
                {
                    "formation": [int(first_a), int(middle_b), int(last_a)],
                    "target_bases": list(target_bases),
                    "count_values": list(count_values),
                    "next_count": int(matched_window["window_start"]),
                    "attempt": int(matched_window["attempt"]),
                    "numbers": list(cluster_order),
                    "scores": dict(cluster_scores),
                    "spins_since_trigger": int(completed_spins_since_trigger),
                    "explanation": (
                        f"Alternancia exata {first_a}-{middle_b}-{last_a} ativa. "
                        f"Janela {matched_window['window_start']}-{matched_window['window_end']} "
                        f"(tentativa {matched_window['attempt']}/{attempts}) com alvo no meio e equivalencias."
                    ),
                }
            )

        if not active_signals:
            if cancelled_items:
                return {
                    "numbers": [],
                    "explanation": "Entrada anulada: alvo apareceu nas 4 rodadas anteriores a primeira entrada.",
                    "pending_items": pending_items,
                    "meta": {
                        "cancelled_signals": cancelled_items,
                    },
                }
            if pending_items:
                min_remaining = min(int(item["remaining"]) for item in pending_items)
                return {
                    "numbers": [],
                    "explanation": f"Padrao em monitoramento. Aguardando {min_remaining} giro(s) para a proxima janela valida.",
                    "pending_items": pending_items,
                    "meta": {},
                }
            return {
                "numbers": [],
                "explanation": "Nenhuma alternancia exata com entrada atrasada ativa no momento.",
                "pending_items": [],
                "meta": {},
            }

        split_contributions: List[Dict[str, Any]] = []
        aggregate_scores: Dict[int, float] = defaultdict(float)
        ordered_numbers: List[int] = []
        seen_numbers: Set[int] = set()

        for index, signal in enumerate(active_signals, start=1):
            for number in signal["numbers"]:
                if int(number) in seen_numbers:
                    continue
                seen_numbers.add(int(number))
                ordered_numbers.append(int(number))
            for number, score in signal["scores"].items():
                aggregate_scores[int(number)] += float(score)

            split_contributions.append(
                {
                    "pattern_id": f"{definition.id}_{signal['formation'][0]}_{signal['formation'][1]}_{signal['next_count']}_{index}",
                    "pattern_name": f"{definition.name} [{signal['formation'][0]}-{signal['formation'][1]}-{signal['formation'][2]}]",
                    "numbers": list(signal["numbers"]),
                    "scores": dict(signal["scores"]),
                    "weight": float(definition.weight),
                    "explanation": str(signal["explanation"]),
                }
            )

        final_scores = {int(n): float(aggregate_scores[n]) for n in ordered_numbers}
        next_counts = ", ".join(str(signal["next_count"]) for signal in active_signals)
        return {
            "numbers": ordered_numbers,
            "scores": final_scores,
            "split_contributions": split_contributions,
            "pending_items": pending_items,
            "explanation": (
                f"Alternancia exata com entrada atrasada ativa em {len(active_signals)} sinal(is). Janela(s): {next_counts}."
            ),
            "meta": {
                "active_signals": active_signals,
                "cancelled_signals": cancelled_items,
            },
        }

    def _eval_color_neighbor_alternation_missing_entry(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        hist = [int(n) for n in history[from_index:] if self._is_valid_number(n)]
        if len(hist) < 2:
            return {"numbers": [], "explanation": "Historico insuficiente para faltante de vizinhos de cor."}

        timeline = list(reversed(hist))  # oldest -> newest
        current_idx = len(timeline) - 1

        wait_spins = max(0, int(definition.params.get("wait_spins", 4)))
        attempts = max(1, int(definition.params.get("attempts_per_count", 6)))
        base_score = float(definition.params.get("base_score", 1.0))
        near_neighbor_score = float(definition.params.get("near_neighbor_score", 0.9))
        far_neighbor_score = float(definition.params.get("far_neighbor_score", 0.75))
        zero_score = float(definition.params.get("zero_score", 0.7))

        active_signals: List[Dict[str, Any]] = []
        pending_items: List[Dict[str, Any]] = []
        cancelled_items: List[Dict[str, Any]] = []

        for pair_end in range(1, len(timeline)):
            first = int(timeline[pair_end - 1])
            second = int(timeline[pair_end])
            missing_target = self._color_neighbor_missing_number(first, second)
            if missing_target is None:
                continue

            _, target_bases = self._exact_repeat_delayed_counts_and_targets(missing_target)
            cluster_order, cluster_scores = self._build_color_neighbor_missing_target_cluster(
                target_bases=target_bases,
                base_score=base_score,
                near_neighbor_score=near_neighbor_score,
                far_neighbor_score=far_neighbor_score,
                zero_score=zero_score,
            )
            if not cluster_order:
                continue

            target_set = set(cluster_scores.keys())
            completed_spins_since_trigger = current_idx - pair_end
            next_round_number = completed_spins_since_trigger + 1

            wait_indices = [pair_end + offset for offset in range(1, wait_spins + 1)]
            observed_wait_indices = [idx for idx in wait_indices if idx <= current_idx]
            if any(int(timeline[idx]) in target_set for idx in observed_wait_indices):
                cancelled_items.append(
                    {
                        "pair": [int(first), int(second)],
                        "missing_target": int(missing_target),
                        "target_bases": list(target_bases),
                        "cluster_order": list(cluster_order),
                    }
                )
                continue

            window_start = int(wait_spins + 1)
            window_end = int(wait_spins + attempts)
            entry_indices = [pair_end + offset for offset in range(window_start, window_end + 1)]
            observed_entry_indices = [idx for idx in entry_indices if idx <= current_idx]
            if any(int(timeline[idx]) in target_set for idx in observed_entry_indices):
                continue

            if next_round_number < window_start:
                pending_items.append(
                    {
                        "pair": [int(first), int(second)],
                        "missing_target": int(missing_target),
                        "target_bases": list(target_bases),
                        "remaining": int(window_start - next_round_number),
                        "spins_since_trigger": int(completed_spins_since_trigger),
                    }
                )
                continue

            if next_round_number > window_end:
                continue

            active_signals.append(
                {
                    "pair": [int(first), int(second)],
                    "missing_target": int(missing_target),
                    "target_bases": list(target_bases),
                    "window_start": int(window_start),
                    "window_end": int(window_end),
                    "attempt": int((next_round_number - window_start) + 1),
                    "numbers": list(cluster_order),
                    "scores": dict(cluster_scores),
                    "spins_since_trigger": int(completed_spins_since_trigger),
                    "explanation": (
                        f"Vizinhos de cor {first}-{second} com faltante {missing_target} ativos. "
                        f"Espera fixa {wait_spins} e janela {window_start}-{window_end} "
                        f"(tentativa {(next_round_number - window_start) + 1}/{attempts})."
                    ),
                }
            )

        if not active_signals:
            if cancelled_items:
                return {
                    "numbers": [],
                    "explanation": "Entrada anulada: alvo apareceu nas 4 rodadas de espera.",
                    "pending_items": pending_items,
                    "meta": {
                        "cancelled_signals": cancelled_items,
                    },
                }
            if pending_items:
                min_remaining = min(int(item["remaining"]) for item in pending_items)
                return {
                    "numbers": [],
                    "explanation": f"Padrao em monitoramento. Aguardando {min_remaining} giro(s) para abrir a janela de entrada.",
                    "pending_items": pending_items,
                    "meta": {},
                }
            return {
                "numbers": [],
                "explanation": "Nenhum faltante de vizinhos de cor com entrada atrasada ativo no momento.",
                "pending_items": [],
                "meta": {},
            }

        split_contributions: List[Dict[str, Any]] = []
        aggregate_scores: Dict[int, float] = defaultdict(float)
        ordered_numbers: List[int] = []
        seen_numbers: Set[int] = set()

        for index, signal in enumerate(active_signals, start=1):
            for number in signal["numbers"]:
                if int(number) in seen_numbers:
                    continue
                seen_numbers.add(int(number))
                ordered_numbers.append(int(number))
            for number, score in signal["scores"].items():
                aggregate_scores[int(number)] += float(score)

            split_contributions.append(
                {
                    "pattern_id": f"{definition.id}_{signal['pair'][0]}_{signal['pair'][1]}_{signal['missing_target']}_{index}",
                    "pattern_name": f"{definition.name} [{signal['pair'][0]}-{signal['pair'][1]}=>{signal['missing_target']}]",
                    "numbers": list(signal["numbers"]),
                    "scores": dict(signal["scores"]),
                    "weight": float(definition.weight),
                    "explanation": str(signal["explanation"]),
                }
            )

        final_scores = {int(n): float(aggregate_scores[n]) for n in ordered_numbers}
        active_windows = ", ".join(
            f"{signal['pair'][0]}-{signal['pair'][1]}:{signal['window_start']}-{signal['window_end']}"
            for signal in active_signals
        )
        return {
            "numbers": ordered_numbers,
            "scores": final_scores,
            "split_contributions": split_contributions,
            "pending_items": pending_items,
            "explanation": (
                f"Faltante de vizinhos de cor com entrada atrasada ativo em {len(active_signals)} sinal(is). Janela(s): {active_windows}."
            ),
            "meta": {
                "active_signals": active_signals,
                "cancelled_signals": cancelled_items,
            },
        }

    def _eval_terminal_alternation_middle_entry(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        hist = [int(n) for n in history[from_index:] if self._is_valid_number(n)]
        if len(hist) < 3:
            return {"numbers": [], "explanation": "Historico insuficiente para alternancia de terminais com alvo no meio."}

        timeline = list(reversed(hist))  # oldest -> newest
        current_idx = len(timeline) - 1

        wait_spins = max(0, int(definition.params.get("wait_spins", 4)))
        attempts = max(1, int(definition.params.get("attempts_per_count", 4)))
        target_score = float(definition.params.get("target_score", 1.0))
        near_neighbor_score = float(definition.params.get("near_neighbor_score", 0.9))
        mid_neighbor_score = float(definition.params.get("mid_neighbor_score", 0.8))
        far_neighbor_score = float(definition.params.get("far_neighbor_score", 0.7))
        zero_score = float(definition.params.get("zero_score", 0.7))
        neighbor_span = max(1, int(definition.params.get("neighbor_span", 3)))

        active_signals: List[Dict[str, Any]] = []
        pending_items: List[Dict[str, Any]] = []
        cancelled_items: List[Dict[str, Any]] = []

        for pattern_end in range(2, len(timeline)):
            first = int(timeline[pattern_end - 2])
            middle = int(timeline[pattern_end - 1])
            third = int(timeline[pattern_end])

            if first == 0 or middle == 0 or third == 0:
                continue
            if (first % 10) != (third % 10):
                continue

            cluster_order, cluster_scores = self._build_terminal_middle_entry_target_cluster(
                target_number=middle,
                target_score=target_score,
                near_neighbor_score=near_neighbor_score,
                mid_neighbor_score=mid_neighbor_score,
                far_neighbor_score=far_neighbor_score,
                zero_score=zero_score,
                span=neighbor_span,
            )
            if not cluster_order:
                continue

            target_set = set(cluster_scores.keys())
            completed_spins_since_trigger = current_idx - pattern_end
            next_round_number = completed_spins_since_trigger + 1

            wait_indices = [pattern_end + offset for offset in range(1, wait_spins + 1)]
            observed_wait_indices = [idx for idx in wait_indices if idx <= current_idx]
            if any(int(timeline[idx]) in target_set for idx in observed_wait_indices):
                cancelled_items.append(
                    {
                        "formation": [int(first), int(middle), int(third)],
                        "target_number": int(middle),
                        "cluster_order": list(cluster_order),
                    }
                )
                continue

            window_start = int(wait_spins + 1)
            window_end = int(wait_spins + attempts)
            entry_indices = [pattern_end + offset for offset in range(window_start, window_end + 1)]
            observed_entry_indices = [idx for idx in entry_indices if idx <= current_idx]
            if any(int(timeline[idx]) in target_set for idx in observed_entry_indices):
                continue

            if next_round_number < window_start:
                pending_items.append(
                    {
                        "formation": [int(first), int(middle), int(third)],
                        "target_number": int(middle),
                        "remaining": int(window_start - next_round_number),
                        "spins_since_trigger": int(completed_spins_since_trigger),
                    }
                )
                continue

            if next_round_number > window_end:
                continue

            active_signals.append(
                {
                    "formation": [int(first), int(middle), int(third)],
                    "target_number": int(middle),
                    "window_start": int(window_start),
                    "window_end": int(window_end),
                    "attempt": int((next_round_number - window_start) + 1),
                    "numbers": list(cluster_order),
                    "scores": dict(cluster_scores),
                    "spins_since_trigger": int(completed_spins_since_trigger),
                    "explanation": (
                        f"Alternancia de terminais {first}-{middle}-{third} ativa. "
                        f"Alvo no meio {middle}. Espera fixa {wait_spins} e janela {window_start}-{window_end} "
                        f"(tentativa {(next_round_number - window_start) + 1}/{attempts})."
                    ),
                }
            )

        if not active_signals:
            if cancelled_items:
                return {
                    "numbers": [],
                    "explanation": "Entrada anulada: alvo apareceu nas 4 rodadas de espera.",
                    "pending_items": pending_items,
                    "meta": {
                        "cancelled_signals": cancelled_items,
                        "future_extension_note": "Expansao por espelho/gemeos do alvo permanece desativada nesta versao.",
                    },
                }
            if pending_items:
                min_remaining = min(int(item["remaining"]) for item in pending_items)
                return {
                    "numbers": [],
                    "explanation": f"Padrao em monitoramento. Aguardando {min_remaining} giro(s) para abrir a janela de entrada.",
                    "pending_items": pending_items,
                    "meta": {
                        "future_extension_note": "Expansao por espelho/gemeos do alvo permanece desativada nesta versao.",
                    },
                }
            return {
                "numbers": [],
                "explanation": "Nenhuma alternancia de terminais com alvo no meio ativa no momento.",
                "pending_items": [],
                "meta": {
                    "future_extension_note": "Expansao por espelho/gemeos do alvo permanece desativada nesta versao.",
                },
            }

        split_contributions: List[Dict[str, Any]] = []
        aggregate_scores: Dict[int, float] = defaultdict(float)
        ordered_numbers: List[int] = []
        seen_numbers: Set[int] = set()

        for index, signal in enumerate(active_signals, start=1):
            for number in signal["numbers"]:
                if int(number) in seen_numbers:
                    continue
                seen_numbers.add(int(number))
                ordered_numbers.append(int(number))
            for number, score in signal["scores"].items():
                aggregate_scores[int(number)] += float(score)

            split_contributions.append(
                {
                    "pattern_id": f"{definition.id}_{signal['formation'][0]}_{signal['formation'][1]}_{signal['formation'][2]}_{index}",
                    "pattern_name": f"{definition.name} [{signal['formation'][0]}-{signal['formation'][1]}-{signal['formation'][2]}]",
                    "numbers": list(signal["numbers"]),
                    "scores": dict(signal["scores"]),
                    "weight": float(definition.weight),
                    "explanation": str(signal["explanation"]),
                }
            )

        final_scores = {int(n): float(aggregate_scores[n]) for n in ordered_numbers}
        active_windows = ", ".join(
            f"{signal['formation'][0]}-{signal['formation'][1]}-{signal['formation'][2]}:{signal['window_start']}-{signal['window_end']}"
            for signal in active_signals
        )
        return {
            "numbers": ordered_numbers,
            "scores": final_scores,
            "split_contributions": split_contributions,
            "pending_items": pending_items,
            "explanation": (
                f"Alternancia de terminais com alvo no meio ativa em {len(active_signals)} sinal(is). Janela(s): {active_windows}."
            ),
            "meta": {
                "active_signals": active_signals,
                "cancelled_signals": cancelled_items,
                "future_extension_note": "Expansao por espelho/gemeos do alvo permanece desativada nesta versao.",
            },
        }

    def _eval_trend_alternation_middle_projection_entry(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        hist = [int(n) for n in history[from_index:] if self._is_valid_number(n)]
        if len(hist) < 3:
            return {"numbers": [], "explanation": "Historico insuficiente para projecao de alternancia pelo numero do meio."}

        timeline = list(reversed(hist))  # oldest -> newest
        current_idx = len(timeline) - 1

        wait_spins = max(0, int(definition.params.get("wait_spins", 4)))
        attempts = max(1, int(definition.params.get("attempts_per_count", 5)))
        target_score = float(definition.params.get("target_score", 1.0))
        neighbor_score = float(definition.params.get("neighbor_score", 0.85))
        zero_score = float(definition.params.get("zero_score", 0.7))

        active_signals: List[Dict[str, Any]] = []
        pending_items: List[Dict[str, Any]] = []
        cancelled_items: List[Dict[str, Any]] = []

        for pattern_end in range(2, len(timeline)):
            first = int(timeline[pattern_end - 2])
            middle = int(timeline[pattern_end - 1])
            third = int(timeline[pattern_end])

            if first == 0 or middle == 0 or third == 0:
                continue

            delta_left = middle - first
            delta_right = third - middle
            if delta_left == 0 or delta_right == 0:
                continue
            if (delta_left > 0 and delta_right > 0) or (delta_left < 0 and delta_right < 0):
                continue

            middle_bases = sorted({int(middle), *self._mirror_numbers(middle)})
            cluster_order, cluster_scores = self._build_middle_trend_projection_target_cluster(
                base_numbers=middle_bases,
                target_score=target_score,
                neighbor_score=neighbor_score,
                zero_score=zero_score,
            )
            if not cluster_order:
                continue

            target_set = set(cluster_scores.keys())
            completed_spins_since_trigger = current_idx - pattern_end
            next_round_number = completed_spins_since_trigger + 1

            wait_indices = [pattern_end + offset for offset in range(1, wait_spins + 1)]
            observed_wait_indices = [idx for idx in wait_indices if idx <= current_idx]
            if any(int(timeline[idx]) in target_set for idx in observed_wait_indices):
                cancelled_items.append(
                    {
                        "formation": [int(first), int(middle), int(third)],
                        "middle_bases": list(middle_bases),
                        "cluster_order": list(cluster_order),
                    }
                )
                continue

            window_start = int(wait_spins + 1)
            window_end = int(wait_spins + attempts)
            entry_indices = [pattern_end + offset for offset in range(window_start, window_end + 1)]
            observed_entry_indices = [idx for idx in entry_indices if idx <= current_idx]
            if any(int(timeline[idx]) in target_set for idx in observed_entry_indices):
                continue

            if next_round_number < window_start:
                pending_items.append(
                    {
                        "formation": [int(first), int(middle), int(third)],
                        "middle_bases": list(middle_bases),
                        "remaining": int(window_start - next_round_number),
                        "spins_since_trigger": int(completed_spins_since_trigger),
                    }
                )
                continue

            if next_round_number > window_end:
                continue

            active_signals.append(
                {
                    "formation": [int(first), int(middle), int(third)],
                    "middle_bases": list(middle_bases),
                    "window_start": int(window_start),
                    "window_end": int(window_end),
                    "attempt": int((next_round_number - window_start) + 1),
                    "numbers": list(cluster_order),
                    "scores": dict(cluster_scores),
                    "spins_since_trigger": int(completed_spins_since_trigger),
                    "explanation": (
                        f"Alternancia de tendencia {first}-{middle}-{third} ativa. "
                        f"Base do meio {middle}. Espera fixa {wait_spins} e janela {window_start}-{window_end} "
                        f"(tentativa {(next_round_number - window_start) + 1}/{attempts})."
                    ),
                }
            )

        if not active_signals:
            if cancelled_items:
                return {
                    "numbers": [],
                    "explanation": "Entrada anulada: alvo apareceu nas 4 rodadas de espera.",
                    "pending_items": pending_items,
                    "meta": {
                        "cancelled_signals": cancelled_items,
                    },
                }
            if pending_items:
                min_remaining = min(int(item["remaining"]) for item in pending_items)
                return {
                    "numbers": [],
                    "explanation": f"Padrao em monitoramento. Aguardando {min_remaining} giro(s) para abrir a janela de entrada.",
                    "pending_items": pending_items,
                    "meta": {},
                }
            return {
                "numbers": [],
                "explanation": "Nenhuma alternancia de tendencia com projecao do meio ativa no momento.",
                "pending_items": [],
                "meta": {},
            }

        split_contributions: List[Dict[str, Any]] = []
        aggregate_scores: Dict[int, float] = defaultdict(float)
        ordered_numbers: List[int] = []
        seen_numbers: Set[int] = set()

        for index, signal in enumerate(active_signals, start=1):
            for number in signal["numbers"]:
                if int(number) in seen_numbers:
                    continue
                seen_numbers.add(int(number))
                ordered_numbers.append(int(number))
            for number, score in signal["scores"].items():
                aggregate_scores[int(number)] += float(score)

            split_contributions.append(
                {
                    "pattern_id": f"{definition.id}_{signal['formation'][0]}_{signal['formation'][1]}_{signal['formation'][2]}_{index}",
                    "pattern_name": f"{definition.name} [{signal['formation'][0]}-{signal['formation'][1]}-{signal['formation'][2]}]",
                    "numbers": list(signal["numbers"]),
                    "scores": dict(signal["scores"]),
                    "weight": float(definition.weight),
                    "explanation": str(signal["explanation"]),
                }
            )

        final_scores = {int(n): float(aggregate_scores[n]) for n in ordered_numbers}
        active_windows = ", ".join(
            f"{signal['formation'][0]}-{signal['formation'][1]}-{signal['formation'][2]}:{signal['window_start']}-{signal['window_end']}"
            for signal in active_signals
        )
        return {
            "numbers": ordered_numbers,
            "scores": final_scores,
            "split_contributions": split_contributions,
            "pending_items": pending_items,
            "explanation": (
                f"Alternancia de tendencia com projecao do meio ativa em {len(active_signals)} sinal(is). Janela(s): {active_windows}."
            ),
            "meta": {
                "active_signals": active_signals,
                "cancelled_signals": cancelled_items,
            },
        }

    def _eval_exact_repeat_delayed_entry(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        hist = [int(n) for n in history[from_index:] if self._is_valid_number(n)]
        if len(hist) < 3:
            return {"numbers": [], "explanation": "Historico insuficiente para repeticao exata com entrada atrasada."}

        timeline = list(reversed(hist))  # oldest -> newest
        current_idx = len(timeline) - 1

        attempts_per_count = max(1, int(definition.params.get("attempts_per_count", 3)))
        cancel_lookback = max(1, int(definition.params.get("cancel_lookback", 4)))
        max_numbers = max(1, int(definition.max_numbers))
        base_score = float(definition.params.get("base_score", 1.0))
        near_neighbor_score = float(definition.params.get("near_neighbor_score", 0.9))
        far_neighbor_score = float(definition.params.get("far_neighbor_score", 0.75))
        zero_score = float(definition.params.get("zero_score", 0.7))

        active_signals: List[Dict[str, Any]] = []
        pending_items: List[Dict[str, Any]] = []
        cancelled_items: List[Dict[str, Any]] = []

        recent_window = [int(n) for n in hist[:cancel_lookback]]

        for pair_end in range(1, len(timeline)):
            base_number = int(timeline[pair_end])
            previous_number = int(timeline[pair_end - 1])

            if base_number == 0 or previous_number != base_number:
                continue

            # Repeticao exata: invalida sequencias com 3+ iguais.
            if pair_end >= 2 and int(timeline[pair_end - 2]) == base_number:
                continue
            if pair_end + 1 < len(timeline) and int(timeline[pair_end + 1]) == base_number:
                continue

            count_values, target_bases = self._exact_repeat_delayed_counts_and_targets(base_number)
            if not count_values or not target_bases:
                continue

            cluster_scores = self._build_exact_repeat_target_cluster(
                target_bases=target_bases,
                base_score=base_score,
                near_neighbor_score=near_neighbor_score,
                far_neighbor_score=far_neighbor_score,
                zero_score=zero_score,
            )
            target_set = set(cluster_scores.keys())
            completed_spins_since_trigger = current_idx - pair_end
            next_round_number = completed_spins_since_trigger + 1

            matched_window: Dict[str, Any] | None = None
            blocked_by_hit = False

            for count_value in count_values:
                window_start = int(count_value)
                window_end = int(count_value + attempts_per_count - 1)
                window_indices = [pair_end + offset for offset in range(window_start, window_end + 1)]
                observed_indices = [idx for idx in window_indices if idx <= current_idx]

                if any(int(timeline[idx]) in target_set for idx in observed_indices):
                    blocked_by_hit = True
                    break

                if next_round_number < window_start:
                    pending_items.append(
                        {
                            "trigger_number": int(base_number),
                            "target_bases": list(target_bases),
                            "count_values": list(count_values),
                            "next_count": int(window_start),
                            "remaining": int(window_start - next_round_number),
                            "spins_since_trigger": int(completed_spins_since_trigger),
                        }
                    )
                    break

                if window_start <= next_round_number <= window_end:
                    matched_window = {
                        "window_start": int(window_start),
                        "window_end": int(window_end),
                        "attempt": int((next_round_number - window_start) + 1),
                    }
                    break

            if blocked_by_hit or matched_window is None:
                continue

            if any(number in target_set for number in recent_window):
                cancelled_items.append(
                    {
                        "trigger_number": int(base_number),
                        "target_bases": list(target_bases),
                        "count_values": list(count_values),
                        "next_count": int(matched_window["window_start"]),
                        "recent_window": list(recent_window),
                    }
                )
                continue

            ranked_signal_numbers = sorted(
                cluster_scores.keys(),
                key=lambda n: (-float(cluster_scores[n]), int(n)),
            )[:max_numbers]
            local_scores = {int(n): float(cluster_scores[n]) for n in ranked_signal_numbers}

            active_signals.append(
                {
                    "trigger_number": int(base_number),
                    "target_bases": list(target_bases),
                    "count_values": list(count_values),
                    "next_count": int(matched_window["window_start"]),
                    "attempt": int(matched_window["attempt"]),
                    "numbers": ranked_signal_numbers,
                    "scores": local_scores,
                    "explanation": (
                        f"Repeticao exata {base_number},{base_number} ativa. "
                        f"Janela {matched_window['window_start']}-{matched_window['window_end']} "
                        f"(tentativa {matched_window['attempt']}/{attempts_per_count}) "
                        f"com alvos {target_bases} + 2 vizinhos + zero."
                    ),
                    "spins_since_trigger": int(completed_spins_since_trigger),
                }
            )

        if not active_signals:
            if cancelled_items:
                return {
                    "numbers": [],
                    "explanation": (
                        "Entrada anulada: alvo do grupo apareceu nos 4 ultimos spins antes da entrada."
                    ),
                    "pending_items": pending_items,
                    "meta": {
                        "cancelled_signals": cancelled_items,
                        "recent_window": recent_window,
                    },
                }
            if pending_items:
                min_remaining = min(int(item["remaining"]) for item in pending_items)
                return {
                    "numbers": [],
                    "explanation": (
                        f"Padrao em monitoramento. Aguardando {min_remaining} giro(s) para a proxima janela valida."
                    ),
                    "pending_items": pending_items,
                    "meta": {
                        "recent_window": recent_window,
                    },
                }
            return {
                "numbers": [],
                "explanation": "Nenhuma repeticao exata com janela atrasada ativa no momento.",
                "pending_items": [],
                "meta": {
                    "recent_window": recent_window,
                },
            }

        aggregate_scores: Dict[int, float] = defaultdict(float)
        split_contributions: List[Dict[str, Any]] = []
        for index, signal in enumerate(active_signals, start=1):
            for number, score in signal["scores"].items():
                aggregate_scores[int(number)] += float(score)

            split_contributions.append(
                {
                    "pattern_id": f"{definition.id}_{signal['trigger_number']}_{signal['next_count']}_{index}",
                    "pattern_name": f"{definition.name} [{signal['trigger_number']}]",
                    "numbers": list(signal["numbers"]),
                    "scores": dict(signal["scores"]),
                    "weight": float(definition.weight),
                    "explanation": str(signal["explanation"]),
                }
            )

        ranked_numbers = sorted(
            aggregate_scores.keys(),
            key=lambda n: (-float(aggregate_scores[n]), int(n)),
        )[:max_numbers]
        final_scores = {int(n): float(aggregate_scores[n]) for n in ranked_numbers}

        next_counts = ", ".join(str(signal["next_count"]) for signal in active_signals)
        return {
            "numbers": ranked_numbers,
            "scores": final_scores,
            "split_contributions": split_contributions,
            "pending_items": pending_items,
            "explanation": (
                f"Repeticao exata com entrada atrasada ativa em {len(active_signals)} sinal(is). "
                f"Janela(s) atual(is): {next_counts}."
            ),
            "meta": {
                "active_signals": active_signals,
                "cancelled_signals": cancelled_items,
                "recent_window": recent_window,
            },
        }

    def _eval_legacy_processing_bridge(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        """
        Bridge dos padrões legacy em apps/signals/patterns (fallback para src/signals/patterns).
        Executa somente módulos com process_roulette e coleta sinais com status=processing.
        """
        max_from_index = int(definition.params.get("max_from_index", 0))
        if from_index > max_from_index:
            return {"numbers": [], "explanation": ""}

        min_history = int(definition.params.get("min_history", 10))
        segment = history[from_index:]
        if len(segment) < min_history:
            return {"numbers": [], "explanation": f"Bridge legacy: histórico insuficiente ({len(segment)}<{min_history})."}

        processing_status = str(definition.params.get("status", "processing")).strip().lower()
        if processing_status != "processing":
            return {"numbers": [], "explanation": "Bridge legacy desativado para status diferente de processing."}

        excluded = {
            str(name).strip()
            for name in definition.params.get("excluded_patterns", [])
            if str(name).strip()
        }
        # Evita loops recursivos (api_monitor chama /api/patterns/final-suggestion).
        excluded.add("api_monitor")
        max_patterns = max(1, int(definition.params.get("max_patterns", 120)))
        per_pattern_cap = max(1, int(definition.params.get("per_pattern_cap", 14)))
        position_decay = max(0.0, min(0.5, float(definition.params.get("position_decay", 0.06))))
        sub_pattern_weight = float(definition.params.get("sub_pattern_weight", definition.weight))

        candidates = self._list_legacy_processing_pattern_paths(excluded_patterns=excluded)
        if not candidates:
            return {"numbers": [], "explanation": "Bridge legacy: nenhum padrão elegível encontrado."}

        roulette = {
            "slug": "api-legacy-bridge",
            "name": "API Legacy Bridge",
            "url": "",
        }
        full_results = [
            {"number": int(n), "index": idx}
            for idx, n in enumerate(segment)
        ]

        scores: Dict[int, float] = defaultdict(float)
        active_patterns: List[str] = []
        evaluated = 0
        split_contributions: List[Dict[str, Any]] = []

        for path in candidates[:max_patterns]:
            signal = self._run_legacy_pattern(
                path,
                roulette,
                list(segment),
                [dict(item) for item in full_results],
            )
            if not isinstance(signal, dict):
                continue

            status = str(signal.get("status", "")).strip().lower()
            if status != "processing":
                continue

            numbers = self._extract_legacy_numbers(signal)
            if not numbers:
                continue

            active_patterns.append(path.stem)
            evaluated += 1
            selected_numbers = numbers[:per_pattern_cap]
            local_scores: Dict[int, float] = {}
            for idx, n in enumerate(selected_numbers):
                score = max(0.05, 1.0 - (idx * position_decay))
                local_scores[n] = round(float(score), 4)
                scores[n] += score
            split_contributions.append(
                {
                    "pattern_id": f"legacy_processing_{path.stem}",
                    "pattern_name": f"Legacy Processing: {path.stem}",
                    "numbers": selected_numbers,
                    "scores": local_scores,
                    "weight": sub_pattern_weight,
                    "explanation": f"Legacy {path.stem} retornou status processing.",
                }
            )

        if not scores:
            return {"numbers": [], "explanation": "Bridge legacy: nenhum padrão retornou processing neste momento."}

        max_numbers = max(1, int(definition.max_numbers))
        ranked_numbers = sorted(scores.keys(), key=lambda n: (-scores[n], n))[:max_numbers]
        final_scores = {n: round(float(scores[n]), 4) for n in ranked_numbers}

        return {
            "numbers": ranked_numbers,
            "scores": final_scores,
            "explanation": f"Bridge legacy ativo: {evaluated} padrao(es) em processing.",
            "split_contributions": split_contributions,
            "meta": {
                "legacy_processing_patterns": active_patterns,
                "legacy_processing_count": len(active_patterns),
            },
        }

    def _list_legacy_processing_pattern_paths(self, excluded_patterns: Set[str]) -> List[Path]:
        if not self._legacy_patterns_root.exists():
            return []

        norm_excluded = {name.strip().lower() for name in excluded_patterns if name}
        signature = self._build_legacy_patterns_signature()
        cache_key = "|".join(sorted(norm_excluded))
        cached = self._legacy_paths_cache.get(cache_key)
        if cached and cached[0] == signature:
            return list(cached[1])

        paths: List[Path] = []
        for path in sorted(self._legacy_patterns_root.glob("*.py")):
            stem = path.stem.strip().lower()
            if stem in norm_excluded:
                continue

            try:
                source = path.read_text(encoding="utf-8")
            except Exception:
                continue

            if "def process_roulette" not in source:
                continue
            if '"processing"' not in source and "'processing'" not in source:
                continue

            # Validação leve para evitar falso positivo de texto/comentário.
            try:
                tree = ast.parse(source, filename=str(path))
            except SyntaxError:
                continue

            has_process_fn = any(
                isinstance(node, ast.FunctionDef) and node.name == "process_roulette"
                for node in tree.body
            )
            if not has_process_fn:
                continue

            paths.append(path)

        self._legacy_paths_cache[cache_key] = (signature, list(paths))
        return paths

    def _build_legacy_patterns_signature(self) -> tuple[tuple[str, int, int], ...]:
        if not self._legacy_patterns_root.exists():
            return ()
        signature: List[tuple[str, int, int]] = []
        for path in sorted(self._legacy_patterns_root.glob("*.py")):
            try:
                stat = path.stat()
                signature.append((path.name, int(stat.st_mtime_ns), int(stat.st_size)))
            except FileNotFoundError:
                continue
        return tuple(signature)

    def _run_legacy_pattern(
        self,
        path: Path,
        roulette: Dict[str, Any],
        history: List[int],
        full_results: List[Dict[str, Any]],
    ) -> Dict[str, Any] | None:
        callable_fn = self._load_legacy_pattern_callable(path)
        if callable_fn is None:
            return None

        try:
            sig = inspect.signature(callable_fn)
            params = list(sig.parameters.values())
            positional = [
                p for p in params
                if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            ]
            has_varargs = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params)
            supports_three = has_varargs or len(positional) >= 3

            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                if supports_three:
                    return callable_fn(roulette, history, full_results)
                return callable_fn(roulette, history)
        except TypeError:
            # Fallback para assinatura não convencional.
            try:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    return callable_fn(roulette, history)
            except Exception:
                return None
        except Exception:
            return None

    def _load_legacy_pattern_callable(self, path: Path) -> Callable[..., Any] | None:
        key = str(path.resolve())
        if key in self._legacy_callable_cache:
            return self._legacy_callable_cache[key]

        try:
            if str(self._project_root) not in sys.path:
                sys.path.insert(0, str(self._project_root))
            if str(self._legacy_signals_root) not in sys.path:
                sys.path.insert(0, str(self._legacy_signals_root))

            module_name = f"_legacy_pattern_{path.stem}_{abs(hash(key))}"
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                self._legacy_callable_cache[key] = None
                return None
            module = importlib.util.module_from_spec(spec)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                spec.loader.exec_module(module)
            fn = getattr(module, "process_roulette", None)
            self._legacy_callable_cache[key] = fn if callable(fn) else None
            return self._legacy_callable_cache[key]
        except Exception:
            self._legacy_callable_cache[key] = None
            return None

    def _extract_legacy_numbers(self, signal: Dict[str, Any]) -> List[int]:
        for key in ("bets", "targets", "suggestion", "numbers"):
            raw = signal.get(key)
            if raw is None:
                continue
            normalized = self._normalize_legacy_numbers(raw)
            if normalized:
                return normalized
        return []

    def _normalize_legacy_numbers(self, raw: Any) -> List[int]:
        flattened = self._flatten_nested_values(raw)
        ordered: List[int] = []
        seen: set[int] = set()
        for value in flattened:
            if not self._is_valid_number(value):
                continue
            n = self._normalize_number(value)
            if n in seen:
                continue
            seen.add(n)
            ordered.append(n)
        return ordered

    def _flatten_nested_values(self, value: Any) -> List[Any]:
        if isinstance(value, dict):
            out: List[Any] = []
            for nested in value.values():
                out.extend(self._flatten_nested_values(nested))
            return out
        if isinstance(value, (list, tuple, set)):
            out: List[Any] = []
            for nested in value:
                out.extend(self._flatten_nested_values(nested))
            return out
        return [value]

    def _terminal_group_rotation_group_for_number(self, number: int) -> str | None:
        """
        Helper claro: número -> grupo (A/B/C) para rotação 369/147/258.
        Retorna None quando o número não pertence aos grupos (ex.: 0, final 0).
        """
        if number == 0:
            return None
        terminal = number % 10
        return TERMINAL_GROUP_ROTATION_BY_FINAL.get(terminal)

    def _terminal_group_rotation_numbers_for_group(self, group_id: str) -> List[int]:
        """
        Helper claro: grupo -> lista completa de números do grupo.
        """
        values = TERMINAL_GROUP_ROTATION_NUMBERS.get(group_id, [])
        return list(values)

    def _eval_terminal_group_rotation_369_147_258(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        """
        Padrão de rotação por grupos de finais:
        - janela temporal: history[from_index + 0], +1, +2 (mais recente -> mais antigo)
        - forma quando os 3 números pertencem a grupos diferentes (A/B/C)
        - zero invalida o padrão
        - aposta no grupo do número mais antigo da janela (history[from_index + 2])
        """
        if len(history) < (from_index + 3):
            return {"numbers": [], "explanation": "Histórico insuficiente para rotação de grupos de finais."}

        hist = history[from_index:]
        n0, n1, n2 = int(hist[0]), int(hist[1]), int(hist[2])  # n0 mais recente, n2 mais antigo da janela

        if n0 == 0 or n1 == 0 or n2 == 0:
            return {"numbers": [], "explanation": "Padrão inválido: zero presente na janela [history[0..2]]."}

        g0 = self._terminal_group_rotation_group_for_number(n0)
        g1 = self._terminal_group_rotation_group_for_number(n1)
        g2 = self._terminal_group_rotation_group_for_number(n2)
        if not g0 or not g1 or not g2:
            return {
                "numbers": [],
                "explanation": "Padrão inválido: número fora dos grupos 369/147/258 na janela [history[0..2]].",
            }

        if len({g0, g1, g2}) != 3:
            return {"numbers": [], "explanation": "Sem rotação completa: os 3 grupos não são distintos."}

        target_group = g2  # grupo do número mais antigo da janela (início do padrão)
        target_numbers = self._terminal_group_rotation_numbers_for_group(target_group)
        max_numbers = max(1, int(definition.max_numbers))
        selected_numbers = target_numbers[:max_numbers]
        scores = {n: 1.0 for n in selected_numbers}

        return {
            "numbers": selected_numbers,
            "scores": scores,
            "explanation": (
                f"Rotação de grupos detectada em [history[0],history[1],history[2]]="
                f"[{n0},{n1},{n2}] => [{g0},{g1},{g2}]. "
                f"Aposta no grupo do número mais antigo ({n2}): grupo {target_group}."
            ),
            "meta": {
                "window_numbers": [n0, n1, n2],
                "window_groups": [g0, g1, g2],
                "start_number": n2,
                "target_group": target_group,
            },
        }

    def _eval_terminal_repeat_sum_neighbors(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        if len(history) < (from_index + 2):
            return {"numbers": [], "explanation": "Historico insuficiente para este padrao."}

        first = history[from_index]
        second = history[from_index + 1]
        t0 = first % 10
        t1 = second % 10
        if t0 != t1:
            return {"numbers": [], "explanation": "Sem repeticao de terminal no gatilho."}

        if len(history) >= (from_index + 3):
            third = history[from_index + 2]
            if third % 10 == t0:
                return {"numbers": [], "explanation": "Sequencia de 3 terminais iguais invalida o gatilho."}

        target_terminal = (self._sum_digits(first) + self._sum_digits(second)) % 10
        include_neighbors = bool(definition.params.get("include_neighbors", True))
        max_numbers = max(1, int(definition.max_numbers))
        result = self._build_target_numbers(target_terminal, include_neighbors, max_numbers)
        per_number_scores = {n: 1.0 for n in result}

        return {
            "numbers": result,
            "scores": per_number_scores,
            "explanation": (
                f"Padrao detectado: {first}, {second} -> alvo terminal {target_terminal}. "
                f"Nucleo terminal/soma + vizinhos."
            ),
        }

    def _eval_terminal_repeat_wait_spins_neighbors(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        if len(history) < (from_index + 2):
            return {"numbers": [], "explanation": "Historico insuficiente para este padrao."}
        include_neighbors = bool(definition.params.get("include_neighbors", True))
        max_numbers = max(1, int(definition.max_numbers))
        dynamic_wait = bool(definition.params.get("wait_from_target_sum", True))

        timeline = list(reversed(history[from_index:]))  # oldest -> newest no contexto avaliado
        if len(timeline) < 2:
            return {"numbers": [], "explanation": "Historico insuficiente para simular pendencias."}

        pending: List[Dict[str, Any]] = []
        activated_now: List[Dict[str, Any]] = []

        for idx in range(1, len(timeline)):
            # Cada novo giro avanca as pendencias anteriores.
            new_pending: List[Dict[str, Any]] = []
            matured: List[Dict[str, Any]] = []
            for item in pending:
                item["remaining"] -= 1
                if item["remaining"] <= 0:
                    matured.append(item)
                else:
                    new_pending.append(item)
            pending = new_pending

            # No ultimo passo da simulacao, os maturados valem para o "numero da vez".
            if idx == len(timeline) - 1 and matured:
                activated_now.extend(matured)

            first = timeline[idx - 1]
            second = timeline[idx]
            t0 = first % 10
            t1 = second % 10
            if t0 != t1:
                continue

            # 3 terminais iguais seguidos invalida o gatilho desta transicao.
            if idx >= 2 and (timeline[idx - 2] % 10) == t0:
                continue

            target_sum = self._sum_digits(first) + self._sum_digits(second)
            target = target_sum % 10
            wait_spins = target_sum if dynamic_wait else max(
                0, int(definition.params.get("wait_spins_after_trigger", 5))
            )
            pending.append(
                {
                    "origin": (first, second),
                    "target": target,
                    "target_sum": target_sum,
                    "remaining": wait_spins,
                }
            )

        if not activated_now:
            if pending:
                min_remaining = min(int(item["remaining"]) for item in pending)
                return {
                    "numbers": [],
                    "explanation": f"Aguardando {min_remaining} giros apos o gatilho para ativar este padrao.",
                    "pending_items": [
                        {
                            "origin": [int(item["origin"][0]), int(item["origin"][1])],
                            "target": int(item["target"]),
                            "target_sum": int(item["target_sum"]),
                            "remaining": int(item["remaining"]),
                        }
                        for item in pending
                    ],
                }
            return {
                "numbers": [],
                "explanation": "Nenhuma pendencia ativa para este padrao no momento.",
                "pending_items": [],
            }

        scores: Dict[int, float] = defaultdict(float)
        activated_targets = [int(item["target"]) for item in activated_now]
        for target in activated_targets:
            nums = self._build_target_numbers(target, include_neighbors, max_numbers)
            for n in nums:
                scores[n] += 1.0

        result = sorted(scores.keys())[:max_numbers]
        scores = {n: scores[n] for n in result}
        origins = ", ".join([f"{a}-{b}" for a, b in (item["origin"] for item in activated_now)])
        return {
            "numbers": result,
            "scores": scores,
            "explanation": (
                f"Pendencias ativadas agora: {len(activated_now)} (gatilhos: {origins}). "
                f"Aplicado terminal/soma + vizinhos para os alvos ativos."
            ),
            "pending_items": [
                {
                    "origin": [int(item["origin"][0]), int(item["origin"][1])],
                    "target": int(item["target"]),
                    "target_sum": int(item["target_sum"]),
                    "remaining": int(item["remaining"]),
                }
                for item in pending
            ],
        }

    def _eval_terminal_repeat_next_sum_wait_neighbors(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        if len(history) < (from_index + 3):
            return {"numbers": [], "explanation": "Historico insuficiente para padrao trio (X,A,B)."}

        include_neighbors = bool(definition.params.get("include_neighbors", True))
        max_numbers = max(1, int(definition.max_numbers))
        min_wait = max(0, int(definition.params.get("min_wait", 0)))
        max_wait = max(60, int(definition.params.get("max_wait", 60)))

        timeline = list(reversed(history[from_index:]))  # oldest -> newest
        if len(timeline) < 3:
            return {"numbers": [], "explanation": "Historico insuficiente para simular trios."}

        pending: List[Dict[str, Any]] = []
        activated_now: List[Dict[str, Any]] = []

        for idx in range(2, len(timeline)):
            # Avanca pendencias a cada novo giro.
            new_pending: List[Dict[str, Any]] = []
            matured: List[Dict[str, Any]] = []
            for item in pending:
                item["remaining"] -= 1
                if item["remaining"] <= 0:
                    matured.append(item)
                else:
                    new_pending.append(item)
            pending = new_pending

            if idx == len(timeline) - 1 and matured:
                activated_now.extend(matured)

            # Trio cronologico: [B, A, X], onde A/B repetem terminal e X define espera.
            b = timeline[idx - 2]
            a = timeline[idx - 1]
            x = timeline[idx]
            if (a % 10) != (b % 10):
                continue

            target_sum = self._sum_digits(a) + self._sum_digits(b)
            target = target_sum % 10
            wait_spins = self._sum_digits(x)
            wait_spins = max(min_wait, min(max_wait, wait_spins))

            pending.append(
                {
                    "origin": (x, a, b),
                    "target": target,
                    "target_sum": target_sum,
                    "wait_from": x,
                    "remaining": wait_spins,
                }
            )

        if not activated_now:
            if pending:
                min_remaining = min(int(item["remaining"]) for item in pending)
                return {
                    "numbers": [],
                    "explanation": (
                        f"Padrao trio ativo em espera. Aguardando {min_remaining} giros para maturar."
                    ),
                    "pending_items": [
                        {
                            "origin": [int(item["origin"][0]), int(item["origin"][1]), int(item["origin"][2])],
                            "target": int(item["target"]),
                            "target_sum": int(item["target_sum"]),
                            "wait_from": int(item["wait_from"]),
                            "remaining": int(item["remaining"]),
                        }
                        for item in pending
                    ],
                }
            return {
                "numbers": [],
                "explanation": "Nenhuma pendencia ativa para padrao trio no momento.",
                "pending_items": [],
            }

        scores: Dict[int, float] = defaultdict(float)
        for item in activated_now:
            nums = self._build_target_numbers(int(item["target"]), include_neighbors, max_numbers)
            for n in nums:
                scores[n] += 1.0

        result = sorted(scores.keys())[:max_numbers]
        scores = {n: scores[n] for n in result}
        origins = ", ".join([f"{x}-{a}-{b}" for x, a, b in (item["origin"] for item in activated_now)])
        return {
            "numbers": result,
            "scores": scores,
            "explanation": (
                f"Padrao trio maturado agora: {len(activated_now)} gatilho(s) ({origins}). "
                f"Aplicado alvo terminal/soma + vizinhos."
            ),
            "pending_items": [
                {
                    "origin": [int(item["origin"][0]), int(item["origin"][1]), int(item["origin"][2])],
                    "target": int(item["target"]),
                    "target_sum": int(item["target_sum"]),
                    "wait_from": int(item["wait_from"]),
                    "remaining": int(item["remaining"]),
                }
                for item in pending
            ],
        }

    def _build_target_numbers(self, target: int, include_neighbors: bool, max_numbers: int) -> List[int]:
        core = {
            n for n in range(0, 37)
            if (n % 10) == target or self._sum_digits(n) == target
        }
        result_set = set(core)
        if include_neighbors:
            for n in core:
                result_set.update(self._neighbors(n))

        result = sorted(result_set)
        if len(result) > max_numbers:
            result = result[:max_numbers]
        return result

    def _eval_skipped_sequence_target_neighbors(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        if len(history) < (from_index + 2):
            return {"numbers": [], "explanation": "Historico insuficiente para este padrao."}

        first = history[from_index]
        second = history[from_index + 1]
        if abs(first - second) != 2:
            return {"numbers": [], "explanation": "Sem sequencia pulada no gatilho atual."}

        missing = (first + second) // 2
        if not (0 <= missing <= 36):
            return {"numbers": [], "explanation": "Numero faltante fora da faixa valida."}

        target = missing % 10
        include_neighbors = bool(definition.params.get("include_neighbors", True))
        max_numbers = max(1, int(definition.max_numbers))
        numbers = self._build_target_numbers(target, include_neighbors, max_numbers)
        scores = {n: 1.0 for n in numbers}

        return {
            "numbers": numbers,
            "scores": scores,
            "explanation": (
                f"Sequencia pulada detectada: {first}, {second}. "
                f"Faltante {missing} -> alvo terminal/soma {target} + vizinhos."
            ),
        }

    def _eval_anchor_return_target_neighbors_mirrors(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        """
        Regra:
        - ancora = numero de referência.
        - alvo = numero encontrado ao contar "ancora" posições para trás.
        - gatilho: numero atual igual à ancora ou aos vizinhos laterais da ancora.
        - aposta: alvo + 2 vizinhos laterais do alvo + espelhos encontrados na jogada.
        """
        hist = history[from_index:]
        if len(hist) < 3:
            return {"numbers": [], "explanation": "Historico insuficiente para este padrao."}

        include_anchor_as_trigger = bool(definition.params.get("include_anchor_as_trigger", True))
        include_neighbor_trigger = bool(definition.params.get("include_neighbor_trigger", True))
        include_mirrors = bool(definition.params.get("include_mirrors", True))
        exclude_zero_anchor = bool(definition.params.get("exclude_zero_anchor", True))
        exclude_zero_target = bool(definition.params.get("exclude_zero_target", False))

        target_score = float(definition.params.get("target_score", 10.0))
        neighbor1_score = float(definition.params.get("neighbor1_score", 6.0))
        neighbor2_score = float(definition.params.get("neighbor2_score", 4.0))
        mirror_score = float(definition.params.get("mirror_score", 3.0))

        max_numbers = max(1, int(definition.max_numbers))
        scan_cap = max(10, int(definition.params.get("max_scan", 220)))
        scan_hist = hist[: min(len(hist), scan_cap)]
        current = int(scan_hist[0])

        mirrors_map = {
            1: 10, 10: 1,
            2: 20, 20: 2,
            3: 30, 30: 3,
            6: 9, 9: 6,
            11: 22, 22: 11,
            12: 21, 21: 12,
            13: 31, 31: 13,
            16: 19, 19: 16,
            23: 32, 32: 23,
            26: 29, 29: 26,
            33: 11,
        }

        candidate_signals: List[Dict[str, Any]] = []

        for anchor_idx, raw_anchor in enumerate(scan_hist):
            anchor = int(raw_anchor)
            if not (0 <= anchor <= 36):
                continue
            if exclude_zero_anchor and anchor == 0:
                continue

            if anchor_idx == 0 and not include_anchor_as_trigger:
                continue

            target_idx = anchor_idx + anchor
            if target_idx >= len(scan_hist):
                continue

            trigger_numbers = {anchor}
            if include_neighbor_trigger:
                trigger_numbers.update(self._neighbors(anchor))

            if current not in trigger_numbers:
                continue

            target = int(scan_hist[target_idx])
            if not (0 <= target <= 36):
                continue
            if exclude_zero_target and target == 0:
                continue

            candidate_signals.append(
                {
                    "anchor": anchor,
                    "anchor_idx": anchor_idx,
                    "target": target,
                    "target_idx": target_idx,
                    "trigger_numbers": sorted(trigger_numbers),
                    "neighbor_triggered": current != anchor,
                }
            )

        if not candidate_signals:
            return {
                "numbers": [],
                "explanation": "Sem gatilho de retorno da ancora para o numero atual.",
            }

        # Priorização:
        # 1) retorno por vizinho lateral (current != anchor),
        # 2) gatilho da posição atual (anchor_idx == 0),
        # 3) fallback para o sinal mais próximo.
        neighbor_returned = [s for s in candidate_signals if bool(s.get("neighbor_triggered", False))]
        current_anchor = [s for s in candidate_signals if int(s["anchor_idx"]) == 0]
        if neighbor_returned:
            selected_signal = sorted(neighbor_returned, key=lambda s: int(s["anchor_idx"]))[0]
        elif current_anchor:
            selected_signal = current_anchor[0]
        else:
            selected_signal = sorted(candidate_signals, key=lambda s: int(s["anchor_idx"]))[0]

        scores: Dict[int, float] = defaultdict(float)
        local_numbers: Set[int] = {int(selected_signal["target"])}
        scores[int(selected_signal["target"])] += target_score

        target_neighbors_1 = self._neighbors(int(selected_signal["target"]))
        for n1 in target_neighbors_1:
            local_numbers.add(n1)
            scores[n1] += neighbor1_score

        for n1 in target_neighbors_1:
            for n2 in self._neighbors(n1):
                if n2 == int(selected_signal["target"]):
                    continue
                local_numbers.add(n2)
                scores[n2] += neighbor2_score

        mirrors_added: List[int] = []
        if include_mirrors:
            for n in list(local_numbers):
                mirror = mirrors_map.get(int(n))
                if mirror is None:
                    continue
                local_numbers.add(int(mirror))
                scores[int(mirror)] += mirror_score
                mirrors_added.append(int(mirror))

        sorted_numbers = sorted(scores.keys(), key=lambda n: (-scores[n], n))[:max_numbers]
        final_scores = {n: round(scores[n], 4) for n in sorted_numbers}
        return {
            "numbers": sorted_numbers,
            "scores": final_scores,
            "explanation": (
                f"Retorno da ancora ativo. Atual={current}; "
                f"ancora={selected_signal['anchor']} (idx={selected_signal['anchor_idx']}) -> "
                f"alvo={selected_signal['target']} (idx_alvo={selected_signal['target_idx']}); "
                f"espelhos={sorted(set(mirrors_added))}"
            ),
        }

    def _eval_terminal_alternation_target_neighbors(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        if len(history) < (from_index + 3):
            return {"numbers": [], "explanation": "Historico insuficiente para alternancia de terminais."}

        first = history[from_index]
        second = history[from_index + 1]
        third = history[from_index + 2]
        t0 = first % 10
        t1 = second % 10
        t2 = third % 10

        # Exemplo esperado: 14,28,4 -> 4,8,4 => alvo 8
        if not (t0 == t2 and t0 != t1):
            return {"numbers": [], "explanation": "Sem alternancia de terminais no gatilho atual."}

        target = t1
        include_neighbors = bool(definition.params.get("include_neighbors", True))
        max_numbers = max(1, int(definition.max_numbers))
        numbers = self._build_target_numbers(target, include_neighbors, max_numbers)
        scores = {n: 1.0 for n in numbers}

        return {
            "numbers": numbers,
            "scores": scores,
            "explanation": (
                f"Alternancia de terminais detectada: {first}, {second}, {third}. "
                f"Alvo terminal/soma {target} + vizinhos."
            ),
        }

    def _eval_sector_alternation_boost(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        if len(history) <= from_index:
            return {"numbers": [], "explanation": "Sem historico para alternancia setorial."}

        window = max(8, int(definition.params.get("window", 20)))
        direct_weight = float(definition.params.get("direct_weight", 1.0))
        neighbor1_weight = float(definition.params.get("neighbor1_weight", 0.65))
        neighbor2_weight = float(definition.params.get("neighbor2_weight", 0.35))
        min_center_distance = max(3, int(definition.params.get("min_center_distance", 6)))
        min_switch_ratio = float(definition.params.get("min_switch_ratio", 0.45))
        target_radius = max(1, int(definition.params.get("target_radius", 2)))
        center_score = float(definition.params.get("center_score", 1.0))
        ring1_score = float(definition.params.get("ring1_score", 0.7))
        ring2_score = float(definition.params.get("ring2_score", 0.45))

        segment = history[from_index : from_index + window]
        if len(segment) < 6:
            return {"numbers": [], "explanation": "Amostra insuficiente para alternancia setorial."}

        score_map: Dict[int, float] = {n: 0.0 for n in range(37)}
        wheel_len = len(WHEEL_ORDER)
        wheel_index = {n: i for i, n in enumerate(WHEEL_ORDER)}

        for n in segment:
            idx = wheel_index.get(n)
            if idx is None:
                continue
            score_map[n] += direct_weight
            d1_left = WHEEL_ORDER[(idx - 1 + wheel_len) % wheel_len]
            d1_right = WHEEL_ORDER[(idx + 1) % wheel_len]
            d2_left = WHEEL_ORDER[(idx - 2 + wheel_len) % wheel_len]
            d2_right = WHEEL_ORDER[(idx + 2) % wheel_len]
            score_map[d1_left] += neighbor1_weight
            score_map[d1_right] += neighbor1_weight
            score_map[d2_left] += neighbor2_weight
            score_map[d2_right] += neighbor2_weight

        def cdist(i1: int, i2: int) -> int:
            raw = abs(i1 - i2)
            return min(raw, wheel_len - raw)

        ranked = sorted(score_map.items(), key=lambda item: (-item[1], item[0]))
        centers: List[int] = []
        for n, _ in ranked:
            idx = wheel_index[n]
            if all(cdist(idx, wheel_index[c]) >= min_center_distance for c in centers):
                centers.append(n)
            if len(centers) >= 2:
                break

        if len(centers) < 2:
            return {"numbers": [], "explanation": "Nao foi possivel separar duas zonas quentes para alternancia."}

        center_a, center_b = centers[0], centers[1]
        idx_a = wheel_index[center_a]
        idx_b = wheel_index[center_b]

        labels: List[str] = []
        for n in segment:
            idx = wheel_index[n]
            labels.append("A" if cdist(idx, idx_a) <= cdist(idx, idx_b) else "B")

        if len(labels) < 2:
            return {"numbers": [], "explanation": "Sem transicoes suficientes para alternancia setorial."}

        switches = sum(1 for i in range(1, len(labels)) if labels[i] != labels[i - 1])
        switch_ratio = switches / float(len(labels) - 1)
        if switch_ratio < min_switch_ratio:
            return {
                "numbers": [],
                "explanation": (
                    f"Alternancia setorial fraca ({switch_ratio:.2f} < {min_switch_ratio:.2f})."
                ),
            }

        last_label = labels[0]  # history[from_index] e o numero mais recente
        target_label = "B" if last_label == "A" else "A"
        target_center = center_b if target_label == "B" else center_a
        target_idx = wheel_index[target_center]

        ring_numbers: List[int] = []
        for dist in range(-target_radius, target_radius + 1):
            ring_numbers.append(WHEEL_ORDER[(target_idx + dist + wheel_len) % wheel_len])

        # score por distancia ao centro alvo
        scores: Dict[int, float] = {}
        for n in ring_numbers:
            d = cdist(wheel_index[n], target_idx)
            if d == 0:
                scores[n] = center_score
            elif d == 1:
                scores[n] = ring1_score
            else:
                scores[n] = ring2_score

        numbers = sorted(set(ring_numbers))
        return {
            "numbers": numbers,
            "scores": scores,
            "explanation": (
                f"Alternancia setorial ativa ({switches}/{len(labels)-1} = {switch_ratio:.2f}). "
                f"Ultima zona: {last_label}; alvo: {target_label} (centro {target_center})."
            ),
        }

    def _eval_local_transition_protection(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        if len(history) <= from_index:
            return {"numbers": [], "explanation": "Sem historico para protecao de transicao local."}

        current = history[from_index]
        window = max(50, int(definition.params.get("window", 500)))
        min_occurrences = max(3, int(definition.params.get("min_occurrences", 8)))
        min_lift = float(definition.params.get("min_lift", 1.2))
        repeat_weight = float(definition.params.get("repeat_weight", 1.0))
        adjacent_weight = float(definition.params.get("adjacent_weight", 0.85))
        digit_sum_weight = float(definition.params.get("digit_sum_weight", 0.8))

        start = from_index + 1
        end = min(len(history) - 1, from_index + window)
        if start > end:
            return {"numbers": [], "explanation": "Janela insuficiente para transicoes locais."}

        occurrences = 0
        transition_counts: Dict[int, int] = defaultdict(int)
        baseline_counts: Dict[int, int] = defaultdict(int)
        total_transitions = 0

        for idx in range(start, end + 1):
            nxt = history[idx - 1]
            baseline_counts[nxt] += 1
            total_transitions += 1
            if history[idx] == current:
                occurrences += 1
                transition_counts[nxt] += 1

        if occurrences < min_occurrences:
            return {
                "numbers": [],
                "explanation": (
                    f"Protetor local inativo: amostra baixa para {current} "
                    f"({occurrences}<{min_occurrences})."
                ),
            }

        raw_candidates = {
            current: repeat_weight,
            current - 1: adjacent_weight,
            current + 1: adjacent_weight,
            self._sum_digits(current): digit_sum_weight,
        }
        candidates = {
            int(n): float(w)
            for n, w in raw_candidates.items()
            if self._is_valid_number(n)
        }

        scores: Dict[int, float] = {}
        lift_debug: List[str] = []
        evidence_factor = max(1.0, min(2.0, occurrences / float(min_occurrences)))
        for n, base_w in candidates.items():
            cond_hits = transition_counts.get(n, 0)
            cond_prob = (cond_hits / occurrences) if occurrences > 0 else 0.0
            baseline_prob = (baseline_counts.get(n, 0) / total_transitions) if total_transitions > 0 else 0.0
            lift = (cond_prob / baseline_prob) if baseline_prob > 1e-9 else (2.0 if cond_prob > 0 else 0.0)
            lift_debug.append(f"{n}:lift={lift:.2f},hit={cond_hits}/{occurrences}")
            if cond_hits <= 0:
                continue
            if lift < min_lift:
                continue
            scores[n] = round(base_w * lift * evidence_factor, 4)

        if not scores:
            return {
                "numbers": [],
                "explanation": (
                    f"Protetor local inativo para {current}: sem lift >= {min_lift:.2f}. "
                    f"Debug: {' | '.join(lift_debug[:6])}"
                ),
            }

        numbers = sorted(scores.keys())
        return {
            "numbers": numbers,
            "scores": scores,
            "explanation": (
                f"Protetor local ativo para {current} com {occurrences} ocorrencias. "
                f"Candidatos: {numbers}. Debug: {' | '.join(lift_debug[:6])}"
            ),
        }

    def _eval_siege_number_boost(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        if len(history) <= from_index:
            return {"numbers": [], "explanation": "Sem historico para cerco de numeros."}

        window = max(2, int(definition.params.get("window", 6)))
        min_occurrences = max(1, int(definition.params.get("min_occurrences", 3)))
        min_streak = max(1, int(definition.params.get("min_streak", 2)))
        freq_weight = float(definition.params.get("freq_weight", 0.7))
        streak_weight = float(definition.params.get("streak_weight", 0.45))
        recency_weight = float(definition.params.get("recency_weight", 0.25))

        current = history[from_index]
        current_candidates = {
            int(n)
            for n in [current, current - 1, current + 1, self._sum_digits(current)]
            if self._is_valid_number(n)
        }
        if not current_candidates:
            return {"numbers": [], "explanation": "Sem candidatos validos para cerco no numero atual."}

        suggestion_windows: List[set[int]] = []
        max_cursor = min(len(history) - 1, from_index + window)
        for cursor in range(from_index + 1, max_cursor + 1):
            anchor = history[cursor]
            prev_set = {
                int(n)
                for n in [anchor, anchor - 1, anchor + 1, self._sum_digits(anchor)]
                if self._is_valid_number(n)
            }
            suggestion_windows.append(prev_set)

        if not suggestion_windows:
            return {"numbers": [], "explanation": "Sem janela valida para cerco de numeros."}

        freq: Dict[int, int] = defaultdict(int)
        for s in suggestion_windows:
            for n in s:
                freq[n] += 1

        scores: Dict[int, float] = {}
        debug_chunks: List[str] = []
        for n in sorted(current_candidates):
            f = int(freq.get(n, 0))
            if f < min_occurrences:
                continue
            streak = 0
            for s in suggestion_windows:
                if n in s:
                    streak += 1
                else:
                    break
            if streak < min_streak:
                continue
            recency = 0
            for idx, s in enumerate(suggestion_windows):
                if n in s:
                    recency = max(recency, window - idx)

            score = (f * freq_weight) + (streak * streak_weight) + (recency * recency_weight / max(1, window))
            scores[n] = round(score, 4)
            debug_chunks.append(f"{n}:f{f}/s{streak}/r{recency}")

        if not scores:
            return {
                "numbers": [],
                "explanation": (
                    f"Cerco inativo para {current}: sem numero com freq>={min_occurrences} e streak>={min_streak}."
                ),
            }

        numbers = sorted(scores.keys())
        return {
            "numbers": numbers,
            "scores": scores,
            "explanation": (
                f"Cerco ativo no numero {current}: {len(numbers)} numero(s) fortes detectados. "
                f"Debug: {' | '.join(debug_chunks[:8])}"
            ),
        }

    def _eval_recent_numbers_penalty(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        if len(history) <= from_index:
            return {"numbers": [], "explanation": "Sem historico para aplicar penalidade de recencia."}

        recent_window = max(1, int(definition.params.get("recent_window", 8)))
        include_neighbors = bool(definition.params.get("include_neighbors", True))
        direct_penalty = float(definition.params.get("direct_penalty", 1.25))
        neighbor_penalty = float(definition.params.get("neighbor_penalty", 0.75))
        frequency_boost = float(definition.params.get("frequency_boost", 0.2))

        recent = history[from_index : from_index + recent_window]
        if not recent:
            return {"numbers": [], "explanation": "Janela de recencia vazia."}

        freq: Dict[int, int] = defaultdict(int)
        for n in recent:
            freq[n] += 1

        scores: Dict[int, float] = defaultdict(float)
        for n, count in freq.items():
            scores[n] += direct_penalty + (max(0, count - 1) * frequency_boost)
            if include_neighbors:
                for nb in self._neighbors(n):
                    scores[nb] += neighbor_penalty

        numbers = sorted(scores.keys())
        return {
            "numbers": numbers,
            "scores": {n: float(scores[n]) for n in numbers},
            "explanation": (
                f"Penalidade de recencia aplicada aos ultimos {recent_window} giros "
                f"(direto + vizinhos)."
            ),
        }

    def _eval_cold_sector_penalty(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        if len(history) <= from_index:
            return {"numbers": [], "explanation": "Sem historico para avaliar zona fria."}

        window = max(6, int(definition.params.get("window", 20)))
        direct_weight = float(definition.params.get("direct_weight", 1.0))
        neighbor1_weight = float(definition.params.get("neighbor1_weight", 0.65))
        neighbor2_weight = float(definition.params.get("neighbor2_weight", 0.35))
        cold_quantile = float(definition.params.get("cold_quantile", 0.30))
        zscore_threshold = float(definition.params.get("zscore_threshold", -0.65))
        min_score_spread = float(definition.params.get("min_score_spread", 1.8))
        depth_multiplier = float(definition.params.get("depth_multiplier", 1.2))
        max_cold_numbers = max(1, int(definition.params.get("max_cold_numbers", 12)))

        segment = history[from_index : from_index + window]
        if not segment:
            return {"numbers": [], "explanation": "Janela vazia para avaliar zona fria."}

        score_map: Dict[int, float] = {n: 0.0 for n in range(37)}

        for n in segment:
            score_map[n] += direct_weight
            if n in WHEEL_ORDER:
                idx = WHEEL_ORDER.index(n)
                d1_left = WHEEL_ORDER[(idx - 1 + len(WHEEL_ORDER)) % len(WHEEL_ORDER)]
                d1_right = WHEEL_ORDER[(idx + 1) % len(WHEEL_ORDER)]
                d2_left = WHEEL_ORDER[(idx - 2 + len(WHEEL_ORDER)) % len(WHEEL_ORDER)]
                d2_right = WHEEL_ORDER[(idx + 2) % len(WHEEL_ORDER)]
                score_map[d1_left] += neighbor1_weight
                score_map[d1_right] += neighbor1_weight
                score_map[d2_left] += neighbor2_weight
                score_map[d2_right] += neighbor2_weight

        all_scores = list(score_map.values())
        if not all_scores:
            return {"numbers": [], "explanation": "Sem pontuacao para avaliar zona fria."}

        min_score = min(all_scores)
        max_score = max(all_scores)
        spread = max_score - min_score
        if spread < min_score_spread:
            return {
                "numbers": [],
                "explanation": (
                    f"Distribuicao recente sem zona fria clara (spread {spread:.2f} < {min_score_spread:.2f})."
                ),
            }

        mean = sum(all_scores) / len(all_scores)
        variance = sum((s - mean) ** 2 for s in all_scores) / len(all_scores)
        std = variance ** 0.5

        ranked_by_cold = sorted(score_map.items(), key=lambda item: (item[1], item[0]))
        quantile_count = max(1, min(37, int(round(37 * max(0.05, min(0.8, cold_quantile))))))
        quantile_candidates = {n for n, _ in ranked_by_cold[:quantile_count]}

        if std > 1e-9:
            z_candidates = {
                n
                for n, sc in score_map.items()
                if ((sc - mean) / std) <= zscore_threshold
            }
        else:
            z_candidates = set()

        if z_candidates:
            cold_candidates = (z_candidates & quantile_candidates) or z_candidates
        else:
            cold_candidates = quantile_candidates

        if not cold_candidates:
            return {"numbers": [], "explanation": "Nenhuma zona fria relevante encontrada na janela."}

        selected = sorted(cold_candidates, key=lambda n: (score_map[n], n))[:max_cold_numbers]
        penalty_scores: Dict[int, float] = {}
        base_spread = spread if spread > 1e-9 else 1.0
        for n in selected:
            depth = max(0.0, mean - score_map[n])
            normalized_depth = depth / base_spread
            penalty_scores[n] = round(1.0 + (normalized_depth * depth_multiplier), 4)

        return {
            "numbers": selected,
            "scores": penalty_scores,
            "explanation": (
                f"Zona fria detectada na janela de {len(segment)} giros: "
                f"{len(selected)} numero(s) penalizados por baixa pontuacao setorial (+/-2 vizinhos)."
            ),
        }

    # ==================== ROBUST MULTI-MODEL PATTERN ====================

    def _eval_robust_multi_model(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        """
        Padrão robusto que combina 9 modelos matemáticos.
        Um número só é considerado gatilho se passar em >= min_models_pass modelos.
        """
        if len(history) <= from_index:
            return {"numbers": [], "explanation": "Historico insuficiente para padrao robusto."}

        # Parâmetros
        window = max(10, int(definition.params.get("window", 20)))
        markov_window = max(50, int(definition.params.get("markov_window", 100)))
        min_models_pass = max(1, int(definition.params.get("min_models_pass", 6)))
        include_neighbors = bool(definition.params.get("include_neighbors", True))
        markov_min_lift = float(definition.params.get("markov_min_lift", 1.2))
        cluster_min_density = float(definition.params.get("cluster_min_density", 0.6))
        autocorr_min_rate = float(definition.params.get("autocorr_min_rate", 0.5))
        autocorr_lags = definition.params.get("autocorr_lags", [1, 3, 5])
        graph_min_centrality = float(definition.params.get("graph_min_centrality", 0.5))
        fibonacci_windows = definition.params.get("fibonacci_windows", [2, 3, 5, 8])
        max_numbers = max(1, int(definition.max_numbers))

        # Segmentos de análise
        short_segment = history[from_index:from_index + window]
        long_segment = history[from_index:from_index + markov_window]

        if len(short_segment) < 10:
            return {"numbers": [], "explanation": "Janela curta insuficiente para padrao robusto."}

        # Fase 1: Identificar candidatos (números frequentes na janela curta)
        freq: Dict[int, int] = defaultdict(int)
        for n in short_segment:
            freq[n] += 1

        avg_freq = len(short_segment) / 37.0
        candidates = [n for n, count in freq.items() if count >= max(1, avg_freq * 0.5)]

        if not candidates:
            return {"numbers": [], "explanation": "Nenhum candidato identificado na janela."}

        # Construir matriz de transições para Markov e Grafos
        transitions: Dict[int, Dict[int, int]] = defaultdict(lambda: defaultdict(int))
        total_transitions = 0
        for i in range(len(long_segment) - 1):
            src = long_segment[i]
            dst = long_segment[i + 1]
            transitions[src][dst] += 1
            total_transitions += 1

        # Fase 2: Avaliar cada candidato nos 9 modelos
        model_results: Dict[int, Dict[str, bool]] = {}
        for candidate in candidates:
            results = {
                "markov": self._robust_markov_check(candidate, transitions, total_transitions, markov_min_lift),
                "modularity": self._robust_modularity_check(candidate, short_segment),
                "cluster": self._robust_cluster_check(candidate, freq, short_segment, cluster_min_density),
                "autocorr": self._robust_autocorr_check(candidate, long_segment, autocorr_lags, autocorr_min_rate),
                "density": self._robust_density_check(candidate, freq, short_segment, cluster_min_density),
                "graph": self._robust_graph_check(candidate, transitions, total_transitions, graph_min_centrality),
                "entropy": self._robust_entropy_check(short_segment, window),
                "conditional": self._robust_conditional_check(candidate, short_segment, transitions),
                "fibonacci": self._robust_fibonacci_check(candidate, short_segment, fibonacci_windows),
            }
            model_results[candidate] = results

        # Fase 3: Filtrar candidatos que passaram em >= min_models_pass modelos
        qualified: Dict[int, int] = {}
        for candidate, results in model_results.items():
            passed = sum(1 for v in results.values() if v)
            if passed >= min_models_pass:
                qualified[candidate] = passed

        if not qualified:
            return {
                "numbers": [],
                "explanation": f"Nenhum numero passou em {min_models_pass}+ modelos. Melhor: {max((sum(1 for v in r.values() if v) for r in model_results.values()), default=0)}/9.",
            }

        # Fase 4: Calcular scores proporcionais
        scores: Dict[int, float] = {}
        for candidate, passed_count in qualified.items():
            # Score proporcional ao número de modelos aprovados
            scores[candidate] = round((passed_count / 9.0), 4)

        # Adicionar vizinhos com score proporcional à distância na roleta
        if include_neighbors:
            neighbors_to_add: Dict[int, float] = {}
            for candidate in qualified.keys():
                # Vizinhos de 1º grau (imediatos) - 70% do score
                for nb in self._neighbors(candidate):
                    if nb not in scores:
                        current_score = neighbors_to_add.get(nb, 0)
                        new_score = round(scores[candidate] * 0.70, 4)
                        neighbors_to_add[nb] = max(current_score, new_score)
                # Vizinhos de 2º grau - 40% do score
                for nb1 in self._neighbors(candidate):
                    for nb2 in self._neighbors(nb1):
                        if nb2 not in scores and nb2 != candidate:
                            current_score = neighbors_to_add.get(nb2, 0)
                            new_score = round(scores[candidate] * 0.40, 4)
                            neighbors_to_add[nb2] = max(current_score, new_score)
            scores.update(neighbors_to_add)

        # Ordenar e limitar
        sorted_numbers = sorted(scores.keys(), key=lambda n: (-scores[n], n))[:max_numbers]
        final_scores = {n: scores[n] for n in sorted_numbers}

        # Usar min_models_pass_primary se configurado
        min_primary = int(definition.params.get("min_models_pass_primary", 7))

        # Construir explicação
        primary_triggers = [n for n in qualified.keys() if qualified[n] >= min_primary]
        secondary_triggers = [n for n in qualified.keys() if qualified[n] < min_primary]

        explanation_parts = []
        if primary_triggers:
            explanation_parts.append(f"Gatilhos primarios ({min_primary}+/9): {primary_triggers}")
        if secondary_triggers:
            explanation_parts.append(f"Gatilhos secundarios ({min_models_pass}-{min_primary-1}/9): {secondary_triggers}")
        explanation_parts.append(f"Total: {len(qualified)} gatilhos + {len(scores) - len(qualified)} vizinhos")

        return {
            "numbers": sorted_numbers,
            "scores": final_scores,
            "explanation": " | ".join(explanation_parts),
        }

    def _robust_markov_check(
        self,
        number: int,
        transitions: Dict[int, Dict[int, int]],
        total_transitions: int,
        min_lift: float,
    ) -> bool:
        """Verifica se o número tem transições com lift >= min_lift e bidirecionalidade."""
        if total_transitions <= 0:
            return False

        outgoing = transitions.get(number, {})
        if not outgoing:
            return False

        total_from_number = sum(outgoing.values())
        if total_from_number < 2:
            return False

        # Verificar se existe pelo menos uma transição bidirecional com lift alto
        for target, count in outgoing.items():
            if count < 2:
                continue
            # Probabilidade condicional P(target | number)
            cond_prob = count / total_from_number
            # Probabilidade base P(target)
            baseline = sum(transitions.get(target, {}).values()) / total_transitions if total_transitions > 0 else 0
            if baseline <= 0:
                continue
            lift = cond_prob / baseline
            if lift >= min_lift:
                # Verificar bidirecionalidade
                reverse_count = transitions.get(target, {}).get(number, 0)
                if reverse_count >= 1:
                    return True
        return False

    def _robust_modularity_check(self, number: int, segment: List[int]) -> bool:
        """Verifica se o número e a maioria da janela pertencem à mesma família modular."""
        # Encontrar família do número
        number_family = None
        for family_name, family_set in MODULAR_FAMILIES.items():
            if number in family_set:
                number_family = family_name
                break

        if number_family is None:
            return False

        family_set = MODULAR_FAMILIES[number_family]
        family_count = sum(1 for n in segment if n in family_set)
        family_ratio = family_count / len(segment) if segment else 0

        return family_ratio >= 0.4  # 40% da janela na mesma família

    def _robust_cluster_check(
        self,
        number: int,
        freq: Dict[int, int],
        segment: List[int],
        min_density: float,
    ) -> bool:
        """Verifica se o número faz parte de um cluster denso."""
        if freq.get(number, 0) < 2:
            return False

        # Identificar cluster: números frequentes próximos na roleta
        wheel_index = {n: i for i, n in enumerate(WHEEL_ORDER)}
        if number not in wheel_index:
            return False

        num_idx = wheel_index[number]
        wheel_len = len(WHEEL_ORDER)

        # Cluster = números dentro de distância 5 na roleta que também são frequentes
        cluster_numbers = set()
        for n, count in freq.items():
            if count < 2:
                continue
            if n not in wheel_index:
                continue
            n_idx = wheel_index[n]
            dist = min(abs(num_idx - n_idx), wheel_len - abs(num_idx - n_idx))
            if dist <= 5:
                cluster_numbers.add(n)

        if len(cluster_numbers) < 2:
            return False

        # Densidade = ocorrências do cluster / tamanho da janela
        cluster_occurrences = sum(1 for n in segment if n in cluster_numbers)
        density = cluster_occurrences / len(segment) if segment else 0

        return density >= min_density

    def _robust_autocorr_check(
        self,
        number: int,
        segment: List[int],
        lags: List[int],
        min_rate: float,
    ) -> bool:
        """Verifica autocorrelação: número reaparece após lags específicos."""
        if len(segment) < max(lags) + 1:
            return False

        correlations = []
        for lag in lags:
            matches = 0
            total = 0
            for i in range(lag, len(segment)):
                if segment[i - lag] == number:
                    total += 1
                    if segment[i] == number:
                        matches += 1
            if total > 0:
                correlations.append(matches / total)

        if not correlations:
            return False

        avg_corr = sum(correlations) / len(correlations)
        return avg_corr >= min_rate

    def _robust_density_check(
        self,
        number: int,
        freq: Dict[int, int],
        segment: List[int],
        min_density: float,
    ) -> bool:
        """Verifica densidade de ocupação local."""
        # Números relacionados ao candidato (mesmo terminal, vizinhos, etc.)
        related = {number}
        related.add(number % 10)  # Terminal
        for n in range(37):
            if n % 10 == number % 10:
                related.add(n)
        related.update(self._neighbors(number))

        occupation = sum(1 for n in segment if n in related)
        density = occupation / len(segment) if segment else 0

        return density >= min_density

    def _robust_graph_check(
        self,
        number: int,
        transitions: Dict[int, Dict[int, int]],
        total_transitions: int,
        min_centrality: float,
    ) -> bool:
        """Verifica métricas de teoria dos grafos: grau e centralidade."""
        if total_transitions <= 0:
            return False

        # Grau de saída
        out_degree = len(transitions.get(number, {}))

        # Grau de entrada
        in_degree = sum(1 for src in transitions.values() if number in src)

        # Centralidade: proporção de transições envolvendo o número
        involvement = sum(transitions.get(number, {}).values())
        for src, targets in transitions.items():
            if number in targets:
                involvement += targets[number]

        centrality = involvement / (total_transitions * 2) if total_transitions > 0 else 0

        return out_degree >= 2 and in_degree >= 2 and centrality >= min_centrality

    def _robust_entropy_check(self, segment: List[int], window: int) -> bool:
        """Verifica entropia diferencial: ΔH <= 0 indica cluster se fechando."""
        if len(segment) < window:
            return True  # Sem dados suficientes, assume positivo

        half = len(segment) // 2
        first_half = segment[half:]
        second_half = segment[:half]

        def calc_entropy(arr: List[int]) -> float:
            if not arr:
                return 0.0
            freq: Dict[int, int] = defaultdict(int)
            for n in arr:
                freq[n] += 1
            total = len(arr)
            entropy = 0.0
            for count in freq.values():
                if count > 0:
                    p = count / total
                    entropy -= p * math.log2(p)
            return entropy

        h_old = calc_entropy(first_half)
        h_new = calc_entropy(second_half)
        delta_h = h_new - h_old

        return delta_h <= 0.1  # Entropia estável ou decrescente

    def _robust_conditional_check(
        self,
        number: int,
        segment: List[int],
        transitions: Dict[int, Dict[int, int]],
    ) -> bool:
        """Verifica transição condicional: número puxa outros somente se condições ativas."""
        # Encontrar os números que o candidato mais puxa
        outgoing = transitions.get(number, {})
        if not outgoing:
            return False

        top_targets = sorted(outgoing.items(), key=lambda x: -x[1])[:3]
        if not top_targets:
            return False

        # Verificar se pelo menos um dos top targets está ativo na janela recente
        recent = set(segment[:5]) if len(segment) >= 5 else set(segment)
        for target, _ in top_targets:
            if target in recent:
                return True

        return False

    def _robust_fibonacci_check(
        self,
        number: int,
        segment: List[int],
        windows: List[int],
    ) -> bool:
        """Verifica se o número apareceu dentro da janela Fibonacci."""
        max_window = max(windows) if windows else 8

        # Encontrar última ocorrência do número
        for i, n in enumerate(segment[:max_window]):
            if n == number:
                # Distância = i (0-indexed, então +1 para giros)
                distance = i + 1
                if distance in windows:
                    return True

        return False

    # ==================== END ROBUST MULTI-MODEL PATTERN ====================

    def _eval_legacy_base_suggestion(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        if focus_number is None or not self._is_valid_number(focus_number):
            return {"numbers": [], "explanation": "Sem numero foco para sugestao base legacy."}

        if len(history) <= from_index:
            return {"numbers": [], "explanation": "Historico insuficiente para sugestao base legacy."}

        arr = history
        occurrences: List[int] = []
        for i in range(from_index, len(arr)):
            if arr[i] == focus_number:
                occurrences.append(i)

        pulled: List[int] = []
        for idx in occurrences:
            if idx - 1 >= from_index:
                pulled.append(arr[idx - 1])

        pulled_counts: Dict[int, int] = defaultdict(int)
        for n in pulled:
            pulled_counts[n] += 1

        bucket = self._legacy_build_bucket(pulled)
        confidence_legacy = self._legacy_confidence(bucket, len(pulled))
        suggestion = self._legacy_build_suggestion(bucket, pulled_counts, len(pulled))
        max_numbers = max(1, int(definition.max_numbers))
        numbers = sorted(set(suggestion))[:max_numbers]
        if not numbers:
            return {
                "numbers": [],
                "explanation": "Sugestao base legacy vazia para o foco atual.",
                "meta": {"legacy_confidence_score": confidence_legacy["score"], "legacy_numbers": []},
            }

        return {
            "numbers": numbers,
            "scores": {n: 1.0 for n in numbers},
            "explanation": f"Sugestao base legacy ativa para numero {focus_number}.",
            "meta": {
                "legacy_confidence_score": confidence_legacy["score"],
                "legacy_confidence_label": confidence_legacy["label"],
                "legacy_numbers": numbers,
            },
        }

    @staticmethod
    def _legacy_dozen(n: int) -> str:
        if n == 0:
            return "Zero"
        if n <= 12:
            return "1ª"
        if n <= 24:
            return "2ª"
        return "3ª"

    @staticmethod
    def _legacy_column(n: int) -> str:
        if n == 0:
            return "Zero"
        col = (n - 1) % 3
        return "C1" if col == 0 else ("C2" if col == 1 else "C3")

    @staticmethod
    def _legacy_highlow(n: int) -> str:
        if n == 0:
            return "Zero"
        return "Baixo" if n <= 18 else "Alto"

    @staticmethod
    def _legacy_parity(n: int) -> str:
        if n == 0:
            return "Zero"
        return "Par" if n % 2 == 0 else "Ímpar"

    @staticmethod
    def _legacy_color(n: int) -> str:
        if n == 0:
            return "green"
        return "red" if n in RED_NUMBERS else "black"

    @staticmethod
    def _legacy_sections(n: int) -> List[str]:
        found = [name for name, nums in SECTION_MAP.items() if n in nums]
        return found if found else ["—"]

    def _legacy_build_bucket(self, pulled: List[int]) -> Dict[str, Dict[str, int]]:
        bucket: Dict[str, Dict[str, int]] = {
            "dozen": {"1ª": 0, "2ª": 0, "3ª": 0, "Zero": 0},
            "column": {"C1": 0, "C2": 0, "C3": 0, "Zero": 0},
            "highlow": {"Baixo": 0, "Alto": 0, "Zero": 0},
            "parity": {"Par": 0, "Ímpar": 0, "Zero": 0},
            "color": {"red": 0, "black": 0, "green": 0},
            "section": {"Jeu Zero": 0, "Voisins": 0, "Orphelins": 0, "Tiers": 0},
            "horse": {"147": 0, "258": 0, "036": 0, "369": 0},
        }
        for n in pulled:
            bucket["dozen"][self._legacy_dozen(n)] += 1
            bucket["column"][self._legacy_column(n)] += 1
            bucket["highlow"][self._legacy_highlow(n)] += 1
            bucket["parity"][self._legacy_parity(n)] += 1
            bucket["color"][self._legacy_color(n)] += 1
            for sec in self._legacy_sections(n):
                if sec in bucket["section"]:
                    bucket["section"][sec] += 1
            term = n % 10
            if term in (1, 4, 7):
                bucket["horse"]["147"] += 1
            if term in (2, 5, 8):
                bucket["horse"]["258"] += 1
            if term in (0, 3, 6):
                bucket["horse"]["036"] += 1
            if term in (3, 6, 9):
                bucket["horse"]["369"] += 1
        return bucket

    def _legacy_confidence(self, bucket: Dict[str, Dict[str, int]], total_pulled: int) -> Dict[str, Any]:
        if total_pulled <= 0:
            return {"score": 0, "label": "Baixa"}

        def max_ratio(obj: Dict[str, int]) -> float:
            max_val = max(obj.values()) if obj else 0
            return (max_val / total_pulled) if total_pulled > 0 else 0.0

        ratios = [
            max_ratio(bucket["dozen"]),
            max_ratio(bucket["column"]),
            max_ratio(bucket["highlow"]),
            max_ratio(bucket["parity"]),
            max_ratio(bucket["color"]),
            max_ratio(bucket["section"]),
            max_ratio(bucket["horse"]),
        ]
        avg = sum(ratios) / len(ratios) if ratios else 0.0
        volume_factor = min(1.0, total_pulled / 15.0)
        score = int(round(avg * volume_factor * 100))
        label = "Baixa"
        if score >= 70:
            label = "Alta"
        elif score >= 50:
            label = "Media"
        return {"score": max(0, min(100, score)), "label": label}

    def _legacy_build_suggestion(
        self,
        bucket: Dict[str, Dict[str, int]],
        pulled_counts: Dict[int, int],
        total_pulled: int,
    ) -> List[int]:
        if total_pulled <= 0:
            return []

        def dominant(obj: Dict[str, int], min_ratio: float = 0.6, min_count: int = 3) -> Dict[str, Any] | None:
            if not obj:
                return None
            key, val = sorted(obj.items(), key=lambda x: x[1], reverse=True)[0]
            if val < min_count:
                return None
            ratio = val / total_pulled if total_pulled > 0 else 0
            if ratio < min_ratio:
                return None
            return {"key": key, "ratio": ratio}

        picks = [
            {"type": "dozen", "pick": dominant(bucket["dozen"], 0.6, 3)},
            {"type": "column", "pick": dominant(bucket["column"], 0.6, 3)},
            {"type": "section", "pick": dominant(bucket["section"], 0.6, 3)},
            {"type": "highlow", "pick": dominant(bucket["highlow"], 0.6, 3)},
            {"type": "parity", "pick": dominant(bucket["parity"], 0.6, 3)},
            {"type": "color", "pick": dominant(bucket["color"], 0.6, 3)},
        ]
        picks = [p for p in picks if p["pick"]]

        base = list(range(1, 37))

        def apply_filter(pick_type: str, key: str) -> None:
            nonlocal base
            if pick_type == "dozen":
                if key == "1ª":
                    base = [n for n in base if 1 <= n <= 12]
                elif key == "2ª":
                    base = [n for n in base if 13 <= n <= 24]
                elif key == "3ª":
                    base = [n for n in base if 25 <= n <= 36]
            elif pick_type == "section" and key in SECTION_MAP:
                allowed = set(SECTION_MAP[key])
                base = [n for n in base if n in allowed]
            elif pick_type == "column":
                if key == "C1":
                    base = [n for n in base if (n - 1) % 3 == 0]
                elif key == "C2":
                    base = [n for n in base if (n - 1) % 3 == 1]
                elif key == "C3":
                    base = [n for n in base if (n - 1) % 3 == 2]
            elif pick_type == "highlow":
                base = [n for n in base if (n <= 18 if key == "Baixo" else n >= 19)]
            elif pick_type == "parity":
                base = [n for n in base if ((n % 2 == 0) if key == "Par" else (n % 2 == 1))]
            elif pick_type == "color":
                base = [n for n in base if self._legacy_color(n) == key]

        for p in picks:
            apply_filter(str(p["type"]), str(p["pick"]["key"]))

        if not base and picks:
            relaxed = sorted(picks, key=lambda p: p["pick"]["ratio"])
            base = list(range(1, 37))
            for p in relaxed[1:]:
                apply_filter(str(p["type"]), str(p["pick"]["key"]))

        if (not base) or (len(base) == 36):
            top_pulled = sorted(pulled_counts.items(), key=lambda x: x[1], reverse=True)[:12]
            return sorted([int(n) for n, _ in top_pulled])

        if len(base) == 1:
            n = base[0]
            return sorted(set([n] + self._neighbors(n)))
        return sorted(base)

    def _eval_color_streak_boost(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        """
        Padrão que detecta sequências de cores (vermelho/preto) e alternâncias.
        - Se houver streak de uma cor, sugere números da cor oposta
        - Se houver alternância perfeita, sugere a cor oposta à última
        """
        if len(history) < (from_index + 3):
            return {"numbers": [], "explanation": "Historico insuficiente para padrao de cores."}

        # Parâmetros
        min_streak = max(2, int(definition.params.get("min_streak", 3)))
        max_streak = max(min_streak, int(definition.params.get("max_streak", 8)))
        alternation_window = max(4, int(definition.params.get("alternation_window", 6)))
        min_alternation_ratio = float(definition.params.get("min_alternation_ratio", 0.8))
        streak_boost_base = float(definition.params.get("streak_boost_base", 1.0))
        streak_boost_increment = float(definition.params.get("streak_boost_increment", 0.15))
        alternation_boost = float(definition.params.get("alternation_boost", 1.2))
        include_neighbors = bool(definition.params.get("include_neighbors", True))
        neighbor_score_ratio = float(definition.params.get("neighbor_score_ratio", 0.6))
        max_numbers = max(1, int(definition.max_numbers))

        # Obter cores recentes (excluindo zero)
        recent_colors: List[str] = []
        recent_numbers: List[int] = []
        for i in range(from_index, min(from_index + max(max_streak, alternation_window) + 2, len(history))):
            n = history[i]
            if n == 0:
                continue
            color = "red" if n in RED_NUMBERS else "black"
            recent_colors.append(color)
            recent_numbers.append(n)
            if len(recent_colors) >= max(max_streak, alternation_window) + 1:
                break

        if len(recent_colors) < min_streak:
            return {"numbers": [], "explanation": "Historico de cores insuficiente."}

        # Detectar streak (sequência de mesma cor)
        streak_color = recent_colors[0]
        streak_count = 1
        for i in range(1, len(recent_colors)):
            if recent_colors[i] == streak_color:
                streak_count += 1
            else:
                break

        # Detectar alternância
        alternation_count = 0
        for i in range(min(alternation_window, len(recent_colors) - 1)):
            if recent_colors[i] != recent_colors[i + 1]:
                alternation_count += 1
        alternation_ratio = alternation_count / (min(alternation_window, len(recent_colors) - 1)) if len(recent_colors) > 1 else 0

        scores: Dict[int, float] = {}
        explanation_parts: List[str] = []

        # Lógica de streak
        if streak_count >= min_streak:
            # Cor oposta tem maior probabilidade
            target_color = "black" if streak_color == "red" else "red"
            target_numbers = list(BLACK_NUMBERS) if target_color == "black" else list(RED_NUMBERS)

            # Score proporcional ao tamanho do streak
            boost = streak_boost_base + (min(streak_count, max_streak) - min_streak) * streak_boost_increment
            boost = min(2.0, boost)  # Cap máximo

            for n in target_numbers:
                scores[n] = round(boost, 4)

            explanation_parts.append(
                f"Streak de {streak_count} {streak_color}s detectado -> boost em {target_color} ({len(target_numbers)} nums, score={boost:.2f})"
            )

        # Lógica de alternância
        elif alternation_ratio >= min_alternation_ratio and len(recent_colors) >= alternation_window:
            # Sugere cor oposta à última
            last_color = recent_colors[0]
            target_color = "black" if last_color == "red" else "red"
            target_numbers = list(BLACK_NUMBERS) if target_color == "black" else list(RED_NUMBERS)

            for n in target_numbers:
                current = scores.get(n, 0)
                scores[n] = round(max(current, alternation_boost), 4)

            explanation_parts.append(
                f"Alternancia detectada ({alternation_ratio:.0%}) -> boost em {target_color}"
            )

        else:
            return {
                "numbers": [],
                "explanation": f"Sem padrao de cores forte (streak={streak_count}, alternancia={alternation_ratio:.0%})."
            }

        # Adicionar vizinhos se configurado
        if include_neighbors and scores:
            neighbors_to_add: Dict[int, float] = {}
            for n, score in list(scores.items()):
                for nb in self._neighbors(n):
                    if nb not in scores and nb != 0:
                        current = neighbors_to_add.get(nb, 0)
                        neighbors_to_add[nb] = max(current, round(score * neighbor_score_ratio, 4))
            scores.update(neighbors_to_add)

        # Ordenar e limitar
        sorted_numbers = sorted(scores.keys(), key=lambda n: (-scores[n], n))[:max_numbers]
        final_scores = {n: scores[n] for n in sorted_numbers}

        return {
            "numbers": sorted_numbers,
            "scores": final_scores,
            "explanation": " | ".join(explanation_parts) if explanation_parts else "Padrao de cores ativo.",
        }

    def _eval_dozen_column_streak_boost(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        """
        Padrão que detecta sequências de dúzias ou colunas.
        Se houver streak em uma dúzia/coluna, sugere números das outras.
        """
        if len(history) < (from_index + 3):
            return {"numbers": [], "explanation": "Historico insuficiente para padrao de duzias/colunas."}

        # Parâmetros
        min_streak = max(2, int(definition.params.get("min_streak", 3)))
        max_streak = max(min_streak, int(definition.params.get("max_streak", 6)))
        streak_boost_base = float(definition.params.get("streak_boost_base", 1.0))
        streak_boost_increment = float(definition.params.get("streak_boost_increment", 0.2))
        favor_cold_dozen = bool(definition.params.get("favor_cold_dozen", True))
        cold_dozen_bonus = float(definition.params.get("cold_dozen_bonus", 0.3))
        max_numbers = max(1, int(definition.max_numbers))

        # Funções auxiliares
        def get_dozen(n: int) -> str | None:
            if n == 0:
                return None
            if 1 <= n <= 12:
                return "1st"
            elif 13 <= n <= 24:
                return "2nd"
            else:
                return "3rd"

        def get_column(n: int) -> str | None:
            if n == 0:
                return None
            if n in COLUMN_MAP["1st"]:
                return "1st"
            elif n in COLUMN_MAP["2nd"]:
                return "2nd"
            else:
                return "3rd"

        # Analisar histórico recente
        recent_dozens: List[str] = []
        recent_columns: List[str] = []
        dozen_counts: Dict[str, int] = {"1st": 0, "2nd": 0, "3rd": 0}
        column_counts: Dict[str, int] = {"1st": 0, "2nd": 0, "3rd": 0}

        window = min(max_streak + 2, len(history) - from_index)
        for i in range(from_index, from_index + window):
            n = history[i]
            dozen = get_dozen(n)
            column = get_column(n)
            if dozen:
                recent_dozens.append(dozen)
                dozen_counts[dozen] += 1
            if column:
                recent_columns.append(column)
                column_counts[column] += 1

        if len(recent_dozens) < min_streak:
            return {"numbers": [], "explanation": "Historico insuficiente."}

        # Detectar streak de dúzia
        dozen_streak = 1
        streak_dozen = recent_dozens[0]
        for i in range(1, len(recent_dozens)):
            if recent_dozens[i] == streak_dozen:
                dozen_streak += 1
            else:
                break

        # Detectar streak de coluna
        column_streak = 1
        streak_column = recent_columns[0]
        for i in range(1, len(recent_columns)):
            if recent_columns[i] == streak_column:
                column_streak += 1
            else:
                break

        scores: Dict[int, float] = {}
        explanation_parts: List[str] = []

        # Lógica de streak de dúzia
        if dozen_streak >= min_streak:
            boost = streak_boost_base + (min(dozen_streak, max_streak) - min_streak) * streak_boost_increment
            boost = min(2.0, boost)

            # Dúzias frias (as que não estão em streak)
            cold_dozens = [d for d in ["1st", "2nd", "3rd"] if d != streak_dozen]

            # Se favor_cold_dozen, dar mais peso à dúzia mais fria
            if favor_cold_dozen:
                cold_dozens.sort(key=lambda d: dozen_counts[d])

            for i, dozen in enumerate(cold_dozens):
                dozen_boost = boost + (cold_dozen_bonus if i == 0 and favor_cold_dozen else 0)
                for n in DOZEN_MAP[dozen]:
                    scores[n] = round(max(scores.get(n, 0), dozen_boost), 4)

            explanation_parts.append(
                f"Streak de {dozen_streak} na {streak_dozen} duzia -> boost nas outras"
            )

        # Lógica de streak de coluna
        if column_streak >= min_streak:
            boost = streak_boost_base + (min(column_streak, max_streak) - min_streak) * streak_boost_increment
            boost = min(2.0, boost)

            cold_columns = [c for c in ["1st", "2nd", "3rd"] if c != streak_column]

            if favor_cold_dozen:
                cold_columns.sort(key=lambda c: column_counts[c])

            for i, column in enumerate(cold_columns):
                col_boost = boost + (cold_dozen_bonus if i == 0 and favor_cold_dozen else 0)
                for n in COLUMN_MAP[column]:
                    current = scores.get(n, 0)
                    # Se já tem score de dúzia, faz média ponderada
                    if current > 0:
                        scores[n] = round((current + col_boost) / 2 * 1.2, 4)  # Bonus por consenso
                    else:
                        scores[n] = round(col_boost, 4)

            explanation_parts.append(
                f"Streak de {column_streak} na {streak_column} coluna -> boost nas outras"
            )

        if not scores:
            return {
                "numbers": [],
                "explanation": f"Sem streak forte (duzia={dozen_streak}, coluna={column_streak})."
            }

        # Ordenar e limitar
        sorted_numbers = sorted(scores.keys(), key=lambda n: (-scores[n], n))[:max_numbers]
        final_scores = {n: scores[n] for n in sorted_numbers}

        return {
            "numbers": sorted_numbers,
            "scores": final_scores,
            "explanation": " | ".join(explanation_parts),
        }

    def _eval_parity_streak_boost(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        """
        Padrão que detecta sequências de paridade (par/ímpar).
        Similar ao color_streak_boost mas para paridade.
        """
        if len(history) < (from_index + 3):
            return {"numbers": [], "explanation": "Historico insuficiente para padrao de paridade."}

        # Parâmetros
        min_streak = max(2, int(definition.params.get("min_streak", 3)))
        max_streak = max(min_streak, int(definition.params.get("max_streak", 7)))
        alternation_window = max(4, int(definition.params.get("alternation_window", 6)))
        min_alternation_ratio = float(definition.params.get("min_alternation_ratio", 0.8))
        streak_boost_base = float(definition.params.get("streak_boost_base", 1.0))
        streak_boost_increment = float(definition.params.get("streak_boost_increment", 0.15))
        alternation_boost = float(definition.params.get("alternation_boost", 1.1))
        include_neighbors = bool(definition.params.get("include_neighbors", True))
        neighbor_score_ratio = float(definition.params.get("neighbor_score_ratio", 0.5))
        max_numbers = max(1, int(definition.max_numbers))

        # Obter paridades recentes (excluindo zero)
        recent_parities: List[str] = []
        for i in range(from_index, min(from_index + max(max_streak, alternation_window) + 2, len(history))):
            n = history[i]
            if n == 0:
                continue
            parity = "even" if n % 2 == 0 else "odd"
            recent_parities.append(parity)
            if len(recent_parities) >= max(max_streak, alternation_window) + 1:
                break

        if len(recent_parities) < min_streak:
            return {"numbers": [], "explanation": "Historico de paridade insuficiente."}

        # Detectar streak
        streak_parity = recent_parities[0]
        streak_count = 1
        for i in range(1, len(recent_parities)):
            if recent_parities[i] == streak_parity:
                streak_count += 1
            else:
                break

        # Detectar alternância
        alternation_count = 0
        for i in range(min(alternation_window, len(recent_parities) - 1)):
            if recent_parities[i] != recent_parities[i + 1]:
                alternation_count += 1
        alternation_ratio = alternation_count / (min(alternation_window, len(recent_parities) - 1)) if len(recent_parities) > 1 else 0

        scores: Dict[int, float] = {}
        explanation_parts: List[str] = []

        # Lógica de streak
        if streak_count >= min_streak:
            target_parity = "odd" if streak_parity == "even" else "even"
            target_numbers = list(ODD_NUMBERS) if target_parity == "odd" else list(EVEN_NUMBERS)

            boost = streak_boost_base + (min(streak_count, max_streak) - min_streak) * streak_boost_increment
            boost = min(2.0, boost)

            for n in target_numbers:
                scores[n] = round(boost, 4)

            explanation_parts.append(
                f"Streak de {streak_count} {'pares' if streak_parity == 'even' else 'impares'} -> boost em {'impares' if target_parity == 'odd' else 'pares'}"
            )

        # Lógica de alternância
        elif alternation_ratio >= min_alternation_ratio and len(recent_parities) >= alternation_window:
            last_parity = recent_parities[0]
            target_parity = "odd" if last_parity == "even" else "even"
            target_numbers = list(ODD_NUMBERS) if target_parity == "odd" else list(EVEN_NUMBERS)

            for n in target_numbers:
                scores[n] = round(alternation_boost, 4)

            explanation_parts.append(
                f"Alternancia de paridade detectada ({alternation_ratio:.0%})"
            )

        else:
            return {
                "numbers": [],
                "explanation": f"Sem padrao de paridade forte (streak={streak_count}, alt={alternation_ratio:.0%})."
            }

        # Adicionar vizinhos se configurado
        if include_neighbors and scores:
            neighbors_to_add: Dict[int, float] = {}
            for n, score in list(scores.items()):
                for nb in self._neighbors(n):
                    if nb not in scores and nb != 0:
                        current = neighbors_to_add.get(nb, 0)
                        neighbors_to_add[nb] = max(current, round(score * neighbor_score_ratio, 4))
            scores.update(neighbors_to_add)

        # Ordenar e limitar
        sorted_numbers = sorted(scores.keys(), key=lambda n: (-scores[n], n))[:max_numbers]
        final_scores = {n: scores[n] for n in sorted_numbers}

        return {
            "numbers": sorted_numbers,
            "scores": final_scores,
            "explanation": " | ".join(explanation_parts),
        }

    def _eval_sector_repeat_penalty(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        """
        Padrão negativo que penaliza números de setores que aparecem muito seguidos.
        """
        if len(history) < (from_index + 3):
            return {"numbers": [], "explanation": "Historico insuficiente."}

        # Parâmetros
        lookback = max(3, int(definition.params.get("lookback", 4)))
        min_sector_repeat = max(2, int(definition.params.get("min_sector_repeat", 3)))
        direct_penalty = float(definition.params.get("direct_penalty", 1.5))
        neighbor_penalty = float(definition.params.get("neighbor_penalty", 0.8))

        # Setores padrão
        sectors_config = definition.params.get("sectors", {})
        sectors: Dict[str, Set[int]] = {
            "jeu_zero": set(sectors_config.get("jeu_zero", [12, 35, 3, 26, 0, 32, 15])),
            "voisins": set(sectors_config.get("voisins", [22, 18, 29, 7, 28, 12, 35, 3, 26, 0, 32, 15, 19, 4, 21, 2, 25])),
            "orphelins": set(sectors_config.get("orphelins", [17, 34, 6, 1, 20, 14, 31, 9])),
            "tiers": set(sectors_config.get("tiers", [27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33])),
        }

        # Analisar últimos números
        recent = history[from_index:from_index + lookback]

        # Contar ocorrências por setor
        sector_counts: Dict[str, int] = {s: 0 for s in sectors}
        for n in recent:
            for sector_name, sector_nums in sectors.items():
                if n in sector_nums:
                    sector_counts[sector_name] += 1

        # Identificar setores com repetição excessiva
        hot_sectors: List[str] = []
        for sector_name, count in sector_counts.items():
            if count >= min_sector_repeat:
                hot_sectors.append(sector_name)

        if not hot_sectors:
            return {"numbers": [], "explanation": "Nenhum setor com repeticao excessiva."}

        # Penalizar números dos setores quentes
        scores: Dict[int, float] = {}
        for sector_name in hot_sectors:
            for n in sectors[sector_name]:
                current = scores.get(n, 0)
                scores[n] = round(current + direct_penalty, 4)
                # Penalizar vizinhos também
                for nb in self._neighbors(n):
                    if nb not in scores:
                        scores[nb] = round(neighbor_penalty, 4)
                    else:
                        scores[nb] = round(scores[nb] + neighbor_penalty * 0.5, 4)

        sorted_numbers = sorted(scores.keys(), key=lambda n: (-scores[n], n))
        final_scores = {n: scores[n] for n in sorted_numbers}

        return {
            "numbers": sorted_numbers,
            "scores": final_scores,
            "explanation": f"Setores quentes penalizados: {hot_sectors}",
        }

    def _eval_hot_numbers_decay_boost(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        """
        Padrão que dá boost a números "quentes" (frequentes recentemente)
        mas com cooldown - ignora os últimos N giros para evitar repetição imediata.
        """
        if len(history) < (from_index + 10):
            return {"numbers": [], "explanation": "Historico insuficiente para numeros quentes."}

        # Parâmetros
        hot_window = max(15, int(definition.params.get("hot_window", 30)))
        cooldown_start = max(2, int(definition.params.get("cooldown_start", 3)))
        cooldown_end = max(cooldown_start + 1, int(definition.params.get("cooldown_end", 8)))
        min_occurrences = max(1, int(definition.params.get("min_occurrences", 2)))
        base_score = float(definition.params.get("base_score", 1.0))
        frequency_multiplier = float(definition.params.get("frequency_multiplier", 0.3))
        recency_decay = float(definition.params.get("recency_decay", 0.85))
        include_neighbors = bool(definition.params.get("include_neighbors", True))
        neighbor_score_ratio = float(definition.params.get("neighbor_score_ratio", 0.5))
        max_numbers = max(1, int(definition.max_numbers))

        # Números no cooldown (muito recentes, ignorar)
        cooldown_numbers: Set[int] = set()
        for i in range(from_index, min(from_index + cooldown_start, len(history))):
            cooldown_numbers.add(history[i])

        # Analisar janela "quente" (após o cooldown)
        hot_start = from_index + cooldown_start
        hot_end = min(from_index + hot_window, len(history))

        if hot_end <= hot_start:
            return {"numbers": [], "explanation": "Janela de analise insuficiente."}

        # Contar frequência e calcular score com decay
        frequency: Dict[int, int] = defaultdict(int)
        weighted_scores: Dict[int, float] = defaultdict(float)

        for i in range(hot_start, hot_end):
            n = history[i]
            if n == 0:
                continue
            frequency[n] += 1
            # Decay baseado na distância temporal
            distance = i - hot_start
            decay_factor = recency_decay ** distance
            weighted_scores[n] += decay_factor

        # Filtrar números que estão no cooldown ou não atingem frequência mínima
        scores: Dict[int, float] = {}
        for n, freq in frequency.items():
            if n in cooldown_numbers:
                continue
            if freq < min_occurrences:
                continue

            # Score = base + frequência * multiplicador + weighted_score normalizado
            score = base_score + (freq * frequency_multiplier) + (weighted_scores[n] * 0.5)
            scores[n] = round(score, 4)

        if not scores:
            return {"numbers": [], "explanation": "Nenhum numero quente fora do cooldown."}

        # Adicionar vizinhos
        if include_neighbors:
            neighbors_to_add: Dict[int, float] = {}
            for n, score in list(scores.items()):
                for nb in self._neighbors(n):
                    if nb not in scores and nb not in cooldown_numbers and nb != 0:
                        current = neighbors_to_add.get(nb, 0)
                        neighbors_to_add[nb] = max(current, round(score * neighbor_score_ratio, 4))
            scores.update(neighbors_to_add)

        # Ordenar e limitar
        sorted_numbers = sorted(scores.keys(), key=lambda n: (-scores[n], n))[:max_numbers]
        final_scores = {n: scores[n] for n in sorted_numbers}

        hot_count = sum(1 for n in sorted_numbers if frequency.get(n, 0) >= min_occurrences)

        return {
            "numbers": sorted_numbers,
            "scores": final_scores,
            "explanation": f"{hot_count} numeros quentes detectados (cooldown={cooldown_start}, janela={hot_window})",
        }

    def _eval_high_low_streak_boost(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        """
        Padrão que detecta sequências de Alto (19-36) vs Baixo (1-18).
        Similar ao parity_streak_boost.
        """
        if len(history) < (from_index + 3):
            return {"numbers": [], "explanation": "Historico insuficiente para padrao alto/baixo."}

        # Parâmetros
        min_streak = max(2, int(definition.params.get("min_streak", 3)))
        max_streak = max(min_streak, int(definition.params.get("max_streak", 7)))
        alternation_window = max(4, int(definition.params.get("alternation_window", 6)))
        min_alternation_ratio = float(definition.params.get("min_alternation_ratio", 0.8))
        streak_boost_base = float(definition.params.get("streak_boost_base", 1.0))
        streak_boost_increment = float(definition.params.get("streak_boost_increment", 0.15))
        alternation_boost = float(definition.params.get("alternation_boost", 1.1))
        include_neighbors = bool(definition.params.get("include_neighbors", True))
        neighbor_score_ratio = float(definition.params.get("neighbor_score_ratio", 0.5))
        max_numbers = max(1, int(definition.max_numbers))

        # Obter classificações recentes (excluindo zero)
        recent_highlow: List[str] = []
        for i in range(from_index, min(from_index + max(max_streak, alternation_window) + 2, len(history))):
            n = history[i]
            if n == 0:
                continue
            hl = "high" if n >= 19 else "low"
            recent_highlow.append(hl)
            if len(recent_highlow) >= max(max_streak, alternation_window) + 1:
                break

        if len(recent_highlow) < min_streak:
            return {"numbers": [], "explanation": "Historico alto/baixo insuficiente."}

        # Detectar streak
        streak_type = recent_highlow[0]
        streak_count = 1
        for i in range(1, len(recent_highlow)):
            if recent_highlow[i] == streak_type:
                streak_count += 1
            else:
                break

        # Detectar alternância
        alternation_count = 0
        for i in range(min(alternation_window, len(recent_highlow) - 1)):
            if recent_highlow[i] != recent_highlow[i + 1]:
                alternation_count += 1
        alternation_ratio = alternation_count / (min(alternation_window, len(recent_highlow) - 1)) if len(recent_highlow) > 1 else 0

        scores: Dict[int, float] = {}
        explanation_parts: List[str] = []

        # Lógica de streak
        if streak_count >= min_streak:
            target_type = "low" if streak_type == "high" else "high"
            target_numbers = list(LOW_NUMBERS) if target_type == "low" else list(HIGH_NUMBERS)

            boost = streak_boost_base + (min(streak_count, max_streak) - min_streak) * streak_boost_increment
            boost = min(2.0, boost)

            for n in target_numbers:
                scores[n] = round(boost, 4)

            explanation_parts.append(
                f"Streak de {streak_count} {'altos' if streak_type == 'high' else 'baixos'} -> boost em {'baixos' if target_type == 'low' else 'altos'}"
            )

        # Lógica de alternância
        elif alternation_ratio >= min_alternation_ratio and len(recent_highlow) >= alternation_window:
            last_type = recent_highlow[0]
            target_type = "low" if last_type == "high" else "high"
            target_numbers = list(LOW_NUMBERS) if target_type == "low" else list(HIGH_NUMBERS)

            for n in target_numbers:
                scores[n] = round(alternation_boost, 4)

            explanation_parts.append(
                f"Alternancia alto/baixo detectada ({alternation_ratio:.0%})"
            )

        else:
            return {
                "numbers": [],
                "explanation": f"Sem padrao alto/baixo forte (streak={streak_count}, alt={alternation_ratio:.0%})."
            }

        # Adicionar vizinhos
        if include_neighbors and scores:
            neighbors_to_add: Dict[int, float] = {}
            for n, score in list(scores.items()):
                for nb in self._neighbors(n):
                    if nb not in scores and nb != 0:
                        current = neighbors_to_add.get(nb, 0)
                        neighbors_to_add[nb] = max(current, round(score * neighbor_score_ratio, 4))
            scores.update(neighbors_to_add)

        sorted_numbers = sorted(scores.keys(), key=lambda n: (-scores[n], n))[:max_numbers]
        final_scores = {n: scores[n] for n in sorted_numbers}

        return {
            "numbers": sorted_numbers,
            "scores": final_scores,
            "explanation": " | ".join(explanation_parts),
        }

    def _eval_sleeping_numbers_boost(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        """
        Padrão que dá boost a números "dormentes" - que não saem há muito tempo.
        Teoria: números têm tendência de "acordar" após longa ausência.
        """
        if len(history) < (from_index + 40):
            return {"numbers": [], "explanation": "Historico insuficiente para numeros dormentes."}

        # Parâmetros
        analysis_window = max(50, int(definition.params.get("analysis_window", 80)))
        min_absence = max(20, int(definition.params.get("min_absence", 40)))
        max_absence = max(min_absence, int(definition.params.get("max_absence", 120)))
        base_score = float(definition.params.get("base_score", 1.0))
        absence_multiplier = float(definition.params.get("absence_multiplier", 0.02))
        cap_score = float(definition.params.get("cap_score", 2.5))
        include_neighbors = bool(definition.params.get("include_neighbors", True))
        neighbor_score_ratio = float(definition.params.get("neighbor_score_ratio", 0.4))
        max_numbers = max(1, int(definition.max_numbers))

        # Calcular última aparição de cada número
        last_seen: Dict[int, int] = {}
        window_end = min(from_index + analysis_window, len(history))

        for i in range(from_index, window_end):
            n = history[i]
            if n not in last_seen:
                last_seen[n] = i - from_index

        # Identificar números dormentes (não apareceram na janela ou apareceram muito cedo)
        scores: Dict[int, float] = {}
        sleeping_numbers: List[tuple[int, int]] = []

        for n in range(0, 37):
            if n not in last_seen:
                # Não apareceu na janela - considerar como ausência máxima
                absence = analysis_window
            else:
                absence = last_seen[n]

            if absence >= min_absence:
                # Score proporcional à ausência
                effective_absence = min(absence, max_absence)
                score = base_score + (effective_absence - min_absence) * absence_multiplier
                score = min(cap_score, score)
                scores[n] = round(score, 4)
                sleeping_numbers.append((n, absence))

        if not scores:
            return {"numbers": [], "explanation": "Nenhum numero dormindo tempo suficiente."}

        # Adicionar vizinhos
        if include_neighbors:
            neighbors_to_add: Dict[int, float] = {}
            for n, score in list(scores.items()):
                for nb in self._neighbors(n):
                    if nb not in scores:
                        current = neighbors_to_add.get(nb, 0)
                        neighbors_to_add[nb] = max(current, round(score * neighbor_score_ratio, 4))
            scores.update(neighbors_to_add)

        sorted_numbers = sorted(scores.keys(), key=lambda n: (-scores[n], n))[:max_numbers]
        final_scores = {n: scores[n] for n in sorted_numbers}

        # Top dormentes para explicação
        sleeping_numbers.sort(key=lambda x: -x[1])
        top_sleeping = sleeping_numbers[:3]

        return {
            "numbers": sorted_numbers,
            "scores": final_scores,
            "explanation": f"{len(sleeping_numbers)} numeros dormentes. Top: {[f'{n}({a}g)' for n, a in top_sleeping]}",
        }

    def _eval_wheel_sector_momentum(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        """
        Detecta concentração de números em uma região do wheel físico
        e sugere a região oposta (momentum reverso).
        """
        if len(history) < (from_index + 3):
            return {"numbers": [], "explanation": "Historico insuficiente para momentum de setor."}

        # Parâmetros
        lookback = max(3, int(definition.params.get("lookback", 5)))
        sector_size = max(5, int(definition.params.get("sector_size", 9)))
        min_concentration = max(2, int(definition.params.get("min_concentration", 3)))
        target_opposite = bool(definition.params.get("target_opposite", True))
        base_score = float(definition.params.get("base_score", 1.0))
        concentration_bonus = float(definition.params.get("concentration_bonus", 0.25))
        include_center_boost = bool(definition.params.get("include_center_boost", True))
        center_boost = float(definition.params.get("center_boost", 1.3))
        max_numbers = max(1, int(definition.max_numbers))

        # Mapear posições no wheel
        wheel_size = len(WHEEL_ORDER)
        num_to_idx = {n: i for i, n in enumerate(WHEEL_ORDER)}

        # Obter posições dos últimos números
        recent_positions: List[int] = []
        for i in range(from_index, min(from_index + lookback, len(history))):
            n = history[i]
            if n in num_to_idx:
                recent_positions.append(num_to_idx[n])

        if len(recent_positions) < min_concentration:
            return {"numbers": [], "explanation": "Posicoes insuficientes para analise."}

        # Encontrar centro de massa no wheel (circular)
        # Usar média circular
        sin_sum = sum(math.sin(2 * math.pi * pos / wheel_size) for pos in recent_positions)
        cos_sum = sum(math.cos(2 * math.pi * pos / wheel_size) for pos in recent_positions)
        center_angle = math.atan2(sin_sum, cos_sum)
        center_idx = int(round((center_angle / (2 * math.pi)) * wheel_size)) % wheel_size

        # Verificar concentração (quantos estão perto do centro)
        concentration = 0
        half_sector = sector_size // 2
        for pos in recent_positions:
            dist = min(abs(pos - center_idx), wheel_size - abs(pos - center_idx))
            if dist <= half_sector:
                concentration += 1

        if concentration < min_concentration:
            return {
                "numbers": [],
                "explanation": f"Concentracao insuficiente ({concentration}/{min_concentration})."
            }

        # Calcular setor oposto
        if target_opposite:
            opposite_center = (center_idx + wheel_size // 2) % wheel_size
        else:
            opposite_center = center_idx

        # Gerar números do setor alvo
        scores: Dict[int, float] = {}
        for offset in range(-half_sector, half_sector + 1):
            idx = (opposite_center + offset) % wheel_size
            n = WHEEL_ORDER[idx]

            # Score maior no centro do setor
            distance_from_center = abs(offset)
            if include_center_boost and distance_from_center == 0:
                score = base_score * center_boost
            else:
                score = base_score + (concentration - min_concentration) * concentration_bonus
                # Decay suave do centro para as bordas
                score *= (1.0 - (distance_from_center / (half_sector + 1)) * 0.3)

            scores[n] = round(score, 4)

        sorted_numbers = sorted(scores.keys(), key=lambda n: (-scores[n], n))[:max_numbers]
        final_scores = {n: scores[n] for n in sorted_numbers}

        center_num = WHEEL_ORDER[center_idx]
        opposite_num = WHEEL_ORDER[opposite_center]

        return {
            "numbers": sorted_numbers,
            "scores": final_scores,
            "explanation": f"Concentracao em {center_num} ({concentration}/{lookback}) -> boost em setor de {opposite_num}",
        }

    def _eval_consecutive_gap_boost(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        """
        Detecta gaps em sequências consecutivas na janela de análise
        e sugere números que preencheriam esses gaps.
        Ex: Se saíram 10, 12, 14 mas não 11, 13 - esses são candidatos.
        """
        if len(history) < (from_index + 20):
            return {"numbers": [], "explanation": "Historico insuficiente para analise de gaps."}

        # Parâmetros
        analysis_window = max(30, int(definition.params.get("analysis_window", 50)))
        min_gap_size = max(2, int(definition.params.get("min_gap_size", 3)))
        max_gap_size = max(min_gap_size, int(definition.params.get("max_gap_size", 8)))
        base_score = float(definition.params.get("base_score", 1.0))
        gap_size_multiplier = float(definition.params.get("gap_size_multiplier", 0.15))
        include_neighbors = bool(definition.params.get("include_neighbors", True))
        neighbor_score_ratio = float(definition.params.get("neighbor_score_ratio", 0.5))
        max_numbers = max(1, int(definition.max_numbers))

        # Coletar números que apareceram na janela
        window_end = min(from_index + analysis_window, len(history))
        appeared: Set[int] = set()
        for i in range(from_index, window_end):
            appeared.add(history[i])

        # Encontrar gaps: números que não apareceram mas têm vizinhos numéricos que apareceram
        scores: Dict[int, float] = {}
        gap_info: List[tuple[int, int]] = []  # (número, tamanho do suporte)

        for n in range(1, 37):  # Excluir 0
            if n in appeared:
                continue

            # Contar vizinhos numéricos que apareceram (n-1, n+1, n-2, n+2, etc.)
            support_count = 0
            for offset in range(1, max_gap_size + 1):
                if (n - offset) in appeared and (n - offset) > 0:
                    support_count += 1
                if (n + offset) in appeared and (n + offset) <= 36:
                    support_count += 1

            if support_count >= min_gap_size:
                # Score proporcional ao suporte
                score = base_score + (support_count - min_gap_size) * gap_size_multiplier
                scores[n] = round(score, 4)
                gap_info.append((n, support_count))

        if not scores:
            return {"numbers": [], "explanation": "Nenhum gap significativo detectado."}

        # Adicionar vizinhos na roleta
        if include_neighbors:
            neighbors_to_add: Dict[int, float] = {}
            for n, score in list(scores.items()):
                for nb in self._neighbors(n):
                    if nb not in scores and nb not in appeared:
                        current = neighbors_to_add.get(nb, 0)
                        neighbors_to_add[nb] = max(current, round(score * neighbor_score_ratio, 4))
            scores.update(neighbors_to_add)

        sorted_numbers = sorted(scores.keys(), key=lambda n: (-scores[n], n))[:max_numbers]
        final_scores = {n: scores[n] for n in sorted_numbers}

        # Top gaps para explicação
        gap_info.sort(key=lambda x: -x[1])
        top_gaps = gap_info[:3]

        return {
            "numbers": sorted_numbers,
            "scores": final_scores,
            "explanation": f"{len(gap_info)} gaps detectados. Top: {[f'{n}(sup={s})' for n, s in top_gaps]}",
        }

    def _eval_wheel_cluster_penalty(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        """
        Padrão negativo que penaliza números em clusters recentes no wheel.
        Se os últimos números estão muito próximos no wheel, penaliza essa região.
        """
        if len(history) < (from_index + 3):
            return {"numbers": [], "explanation": "Historico insuficiente."}

        # Parâmetros
        lookback = max(3, int(definition.params.get("lookback", 5)))
        cluster_radius = max(2, int(definition.params.get("cluster_radius", 4)))
        min_cluster_count = max(2, int(definition.params.get("min_cluster_count", 3)))
        direct_penalty = float(definition.params.get("direct_penalty", 1.2))
        neighbor_penalty = float(definition.params.get("neighbor_penalty", 0.6))
        decay_factor = float(definition.params.get("decay_factor", 0.85))

        # Mapear posições
        wheel_size = len(WHEEL_ORDER)
        num_to_idx = {n: i for i, n in enumerate(WHEEL_ORDER)}

        # Obter posições recentes
        recent_positions: List[int] = []
        recent_numbers: List[int] = []
        for i in range(from_index, min(from_index + lookback, len(history))):
            n = history[i]
            if n in num_to_idx:
                recent_positions.append(num_to_idx[n])
                recent_numbers.append(n)

        if len(recent_positions) < min_cluster_count:
            return {"numbers": [], "explanation": "Posicoes insuficientes."}

        # Identificar clusters (regiões com alta concentração)
        cluster_centers: List[int] = []
        for pos in recent_positions:
            # Contar quantos outros estão perto
            nearby = 0
            for other_pos in recent_positions:
                dist = min(abs(pos - other_pos), wheel_size - abs(pos - other_pos))
                if dist <= cluster_radius and dist > 0:
                    nearby += 1
            if nearby >= min_cluster_count - 1:
                cluster_centers.append(pos)

        if not cluster_centers:
            return {"numbers": [], "explanation": "Nenhum cluster detectado."}

        # Penalizar números nos clusters
        scores: Dict[int, float] = {}
        penalized_regions: Set[int] = set()

        for center in cluster_centers:
            for offset in range(-cluster_radius, cluster_radius + 1):
                idx = (center + offset) % wheel_size
                n = WHEEL_ORDER[idx]
                penalized_regions.add(n)

                distance = abs(offset)
                if distance == 0:
                    penalty = direct_penalty
                else:
                    penalty = direct_penalty * (decay_factor ** distance)

                current = scores.get(n, 0)
                scores[n] = round(current + penalty, 4)

                # Penalizar vizinhos também
                for nb in self._neighbors(n):
                    if nb not in scores:
                        scores[nb] = round(neighbor_penalty, 4)
                    else:
                        scores[nb] = round(scores[nb] + neighbor_penalty * 0.5, 4)

        sorted_numbers = sorted(scores.keys(), key=lambda n: (-scores[n], n))
        final_scores = {n: scores[n] for n in sorted_numbers}

        return {
            "numbers": sorted_numbers,
            "scores": final_scores,
            "explanation": f"Cluster detectado com {len(cluster_centers)} centros, {len(penalized_regions)} numeros penalizados",
        }

    def _get_fallback_suggestion(
        self,
        history: List[int],
        from_index: int,
        max_numbers: int,
    ) -> Dict[str, Any]:
        """
        Fallback inteligente quando nenhum padrão gera sugestão.
        Usa estratégia híbrida baseada em frequência e distribuição.
        """
        if len(history) < (from_index + 20):
            return {
                "numbers": [],
                "explanation": "Historico insuficiente para fallback.",
                "is_fallback": True,
            }

        window = min(100, len(history) - from_index)
        segment = history[from_index:from_index + window]

        # Contar frequência
        freq: Dict[int, int] = defaultdict(int)
        for n in segment:
            freq[n] += 1

        # Encontrar números sub-representados (deveriam ter aparecido mais)
        expected_freq = window / 37.0
        scores: Dict[int, float] = {}

        for n in range(0, 37):
            actual = freq.get(n, 0)
            deficit = expected_freq - actual
            if deficit > 0:
                # Score proporcional ao déficit
                scores[n] = round(0.5 + deficit * 0.3, 4)

        if not scores:
            return {
                "numbers": [],
                "explanation": "Fallback nao gerou sugestoes.",
                "is_fallback": True,
            }

        sorted_numbers = sorted(scores.keys(), key=lambda n: (-scores[n], n))[:max_numbers]
        final_scores = {n: scores[n] for n in sorted_numbers}

        return {
            "numbers": sorted_numbers,
            "scores": final_scores,
            "explanation": f"Fallback: {len(sorted_numbers)} numeros sub-representados na janela de {window}",
            "is_fallback": True,
        }

    def update_pattern_hit_rate(self, pattern_id: str, hit: bool) -> None:
        """
        Atualiza o hit rate de um padrão (para correlação).
        Usa média móvel exponencial.
        """
        alpha = 0.1  # Fator de suavização
        current = self._pattern_hit_rates.get(pattern_id, 0.5)
        new_value = 1.0 if hit else 0.0
        self._pattern_hit_rates[pattern_id] = current * (1 - alpha) + new_value * alpha

    def get_pattern_correlation_boost(self, pattern_id: str) -> float:
        """
        Retorna um multiplicador baseado no hit rate histórico do padrão.
        Padrões com bom histórico recebem boost.
        Inclui decay por misses consecutivos.
        """
        hit_rate = self._pattern_hit_rates.get(pattern_id, 0.5)
        miss_streak = self._pattern_miss_streak.get(pattern_id, 0)

        # Base: mapear hit_rate para multiplicador
        base_mult = 0.6 + (hit_rate * 0.8)

        # Decay por misses consecutivos: -5% por miss, até -30%
        decay = min(0.30, miss_streak * 0.05)
        final_mult = max(0.5, base_mult - decay)

        return final_mult

    def record_pattern_result(self, pattern_id: str, hit: bool) -> None:
        """
        Registra resultado de um padrão (hit ou miss).
        Atualiza hit rate e streak de misses para decay.
        """
        # Atualizar hit rate
        self.update_pattern_hit_rate(pattern_id, hit)

        # Atualizar miss streak
        if hit:
            self._pattern_miss_streak[pattern_id] = 0
        else:
            current_streak = self._pattern_miss_streak.get(pattern_id, 0)
            self._pattern_miss_streak[pattern_id] = current_streak + 1

    def calculate_volatility(self, history: List[int], window: int = 30) -> float:
        """
        Calcula a volatilidade recente baseada na dispersão dos números.
        Retorna valor entre 0 (baixa) e 1 (alta).
        """
        if len(history) < window:
            return 0.5

        segment = history[:window]

        # Contar frequência
        freq: Dict[int, int] = defaultdict(int)
        for n in segment:
            freq[n] += 1

        # Calcular entropia normalizada
        total = len(segment)
        entropy = 0.0
        for count in freq.values():
            if count > 0:
                p = count / total
                entropy -= p * math.log2(p + 1e-10)

        # Normalizar: max entropia para 37 números = log2(37) ≈ 5.2
        max_entropy = math.log2(37)
        normalized_entropy = entropy / max_entropy

        # Alta entropia = alta volatilidade
        self._last_volatility = normalized_entropy
        return normalized_entropy

    def get_dynamic_threshold_multiplier(self, history: List[int]) -> float:
        """
        Retorna multiplicador para thresholds baseado na volatilidade.
        Alta volatilidade -> thresholds mais altos (mais conservador)
        Baixa volatilidade -> thresholds mais baixos (mais agressivo)
        """
        volatility = self.calculate_volatility(history)

        # Mapear: vol 0.3 -> mult 0.85, vol 0.5 -> mult 1.0, vol 0.7 -> mult 1.15
        multiplier = 0.7 + (volatility * 0.6)
        return max(0.8, min(1.2, multiplier))

    def normalize_scores(self, scores: Dict[int, float]) -> Dict[int, float]:
        """
        Normaliza scores para o intervalo [0, 1].
        Evita que um padrão domine os outros.
        """
        if not scores:
            return {}

        min_score = min(scores.values())
        max_score = max(scores.values())
        score_range = max_score - min_score

        if score_range < 0.001:
            # Todos os scores são iguais
            return {n: 0.5 for n in scores}

        return {
            n: round((score - min_score) / score_range, 4)
            for n, score in scores.items()
        }

    # ========================================================================
    # Módulos de Melhoria de Assertividade
    # ========================================================================

    @property
    def correlation_matrix(self) -> "CorrelationMatrix":
        """Lazy loading do módulo de correlação."""
        if self._correlation_matrix is None:
            from api.services.pattern_correlation import correlation_matrix
            self._correlation_matrix = correlation_matrix
        return self._correlation_matrix

    @property
    def decay_manager(self) -> "PatternDecayManager":
        """Lazy loading do módulo de decay."""
        if self._pattern_decay is None:
            from api.services.pattern_decay import pattern_decay
            self._pattern_decay = pattern_decay
        return self._pattern_decay

    @property
    def filter_system(self) -> "SuggestionFilter":
        """Lazy loading do módulo de filtros."""
        if self._suggestion_filter is None:
            from api.services.suggestion_filter import suggestion_filter
            self._suggestion_filter = suggestion_filter
        return self._suggestion_filter

    def get_decay_multiplier(self, pattern_id: str) -> float:
        """
        Retorna multiplicador de decay para o padrão.
        Integra com o módulo pattern_decay.
        """
        try:
            return self.decay_manager.get_multiplier(pattern_id)
        except Exception:
            return 1.0

    def is_pattern_disabled_by_decay(self, pattern_id: str) -> bool:
        """Verifica se padrão está desabilitado por decay excessivo."""
        try:
            return self.decay_manager.is_disabled(pattern_id)
        except Exception:
            return False

    def get_correlation_boost(self, active_patterns: List[str], target_number: int | None = None) -> float:
        """
        Retorna boost baseado em correlação entre padrões ativos.
        Integra com o módulo pattern_correlation.
        """
        try:
            return self.correlation_matrix.compute_correlation_boost(
                active_patterns=active_patterns,
                target_number=target_number,
            )
        except Exception:
            return 1.0

    def apply_suggestion_filter(
        self,
        positive_contributions: List[Dict[str, Any]],
        confidence_context: Dict[str, float],
        confidence_score: int,
    ) -> Dict[str, Any]:
        """
        Aplica filtros de qualidade na sugestão.
        Retorna dict com 'passed' e 'reason'.
        """
        try:
            result = self.filter_system.should_suggest(
                positive_contributions=positive_contributions,
                confidence_context=confidence_context,
                confidence_score=confidence_score,
            )
            return result.to_dict()
        except Exception:
            return {"passed": True, "reason": None, "filter_details": {}}

    def record_signal_result(
        self,
        active_patterns: List[str],
        hit: bool,
        suggested_numbers: List[int],
        actual_number: int | None = None,
    ) -> None:
        """
        Registra resultado de um sinal para todos os módulos.
        Atualiza correlação, decay, e hit rates internos.
        """
        try:
            # Atualiza correlação
            self.correlation_matrix.update_correlation(
                active_patterns=active_patterns,
                hit=hit,
                suggested_numbers=suggested_numbers,
                actual_number=actual_number,
            )
            self.correlation_matrix.save()

            # Atualiza decay para cada padrão
            self.decay_manager.record_batch_result(active_patterns, hit)
            self.decay_manager.save()

            # Atualiza hit rates internos
            for pattern_id in active_patterns:
                self.record_pattern_result(pattern_id, hit)
        except Exception as exc:
            logger.warning("Error recording signal result: %s", exc)

    def _eval_finals_pattern_boost(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        """
        Padrão de "finais" - números que terminam com o mesmo dígito.
        Ex: Final 7 = 7, 17, 27
        """
        if len(history) < (from_index + 5):
            return {"numbers": [], "explanation": "Historico insuficiente para padrao de finais."}

        # Parâmetros
        lookback = max(5, int(definition.params.get("lookback", 10)))
        min_final_repeat = max(2, int(definition.params.get("min_final_repeat", 3)))
        boost_same_final = bool(definition.params.get("boost_same_final", True))
        boost_sequential_final = bool(definition.params.get("boost_sequential_final", True))
        same_final_score = float(definition.params.get("same_final_score", 1.5))
        sequential_final_score = float(definition.params.get("sequential_final_score", 1.2))
        include_neighbors = bool(definition.params.get("include_neighbors", True))
        neighbor_score_ratio = float(definition.params.get("neighbor_score_ratio", 0.4))
        max_numbers = max(1, int(definition.max_numbers))

        # Analisar finais recentes
        recent = history[from_index:from_index + lookback]
        final_counts: Dict[int, int] = defaultdict(int)
        recent_finals: List[int] = []

        for n in recent:
            final = n % 10
            final_counts[final] += 1
            recent_finals.append(final)

        scores: Dict[int, float] = {}
        explanation_parts: List[str] = []

        # Detectar final repetido
        hot_finals: List[tuple[int, int]] = []
        for final, count in final_counts.items():
            if count >= min_final_repeat:
                hot_finals.append((final, count))

        if hot_finals and boost_same_final:
            hot_finals.sort(key=lambda x: -x[1])
            for final, count in hot_finals:
                final_numbers = self._finals_map.get(final, [])
                boost = same_final_score + (count - min_final_repeat) * 0.2
                for n in final_numbers:
                    scores[n] = round(max(scores.get(n, 0), boost), 4)
            explanation_parts.append(f"Finais quentes: {[f'{f}({c}x)' for f, c in hot_finals[:3]]}")

        # Detectar sequência de finais (ex: 1, 2, 3 ou 7, 8, 9)
        if boost_sequential_final and len(recent_finals) >= 3:
            for i in range(len(recent_finals) - 2):
                f1, f2, f3 = recent_finals[i], recent_finals[i+1], recent_finals[i+2]
                # Verificar sequência ascendente ou descendente
                if (f2 == (f1 + 1) % 10 and f3 == (f2 + 1) % 10) or \
                   (f2 == (f1 - 1) % 10 and f3 == (f2 - 1) % 10):
                    # Próximo final esperado
                    if f3 == (f2 + 1) % 10:  # Ascendente
                        next_final = (f3 + 1) % 10
                    else:  # Descendente
                        next_final = (f3 - 1) % 10

                    final_numbers = self._finals_map.get(next_final, [])
                    for n in final_numbers:
                        current = scores.get(n, 0)
                        scores[n] = round(max(current, sequential_final_score), 4)
                    explanation_parts.append(f"Sequencia {f1}->{f2}->{f3}, proximo final: {next_final}")
                    break

        if not scores:
            return {"numbers": [], "explanation": "Sem padrao de finais detectado."}

        # Adicionar vizinhos
        if include_neighbors:
            neighbors_to_add: Dict[int, float] = {}
            for n, score in list(scores.items()):
                for nb in self._neighbors(n):
                    if nb not in scores:
                        current = neighbors_to_add.get(nb, 0)
                        neighbors_to_add[nb] = max(current, round(score * neighbor_score_ratio, 4))
            scores.update(neighbors_to_add)

        sorted_numbers = sorted(scores.keys(), key=lambda n: (-scores[n], n))[:max_numbers]
        final_scores = {n: scores[n] for n in sorted_numbers}

        return {
            "numbers": sorted_numbers,
            "scores": final_scores,
            "explanation": " | ".join(explanation_parts) if explanation_parts else "Padrao de finais ativo.",
        }

    def _eval_volatility_detector(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        """
        Detecta volatilidade e ajusta estratégia.
        Alta volatilidade -> espalhar apostas
        Baixa volatilidade -> concentrar em números quentes
        """
        if len(history) < (from_index + 20):
            return {"numbers": [], "explanation": "Historico insuficiente para detector de volatilidade."}

        # Parâmetros
        short_window = max(10, int(definition.params.get("short_window", 15)))
        long_window = max(30, int(definition.params.get("long_window", 50)))
        high_vol_threshold = float(definition.params.get("high_volatility_threshold", 0.7))
        low_vol_threshold = float(definition.params.get("low_volatility_threshold", 0.3))
        spread_sector_size = max(8, int(definition.params.get("spread_sector_size", 12)))
        concentrate_top_n = max(5, int(definition.params.get("concentrate_top_n", 8)))
        base_score = float(definition.params.get("base_score", 1.0))
        volatility_bonus = float(definition.params.get("volatility_bonus", 0.3))
        max_numbers = max(1, int(definition.max_numbers))

        # Calcular volatilidade de curto e longo prazo
        short_segment = history[from_index:from_index + short_window]
        long_segment = history[from_index:from_index + min(long_window, len(history) - from_index)]

        short_vol = self.calculate_volatility(short_segment, len(short_segment))
        long_vol = self.calculate_volatility(long_segment, len(long_segment))

        # Média ponderada (curto prazo mais importante)
        current_vol = short_vol * 0.7 + long_vol * 0.3

        scores: Dict[int, float] = {}
        explanation_parts: List[str] = []

        if current_vol >= high_vol_threshold:
            # Alta volatilidade: espalhar apostas em setores
            explanation_parts.append(f"Alta volatilidade ({current_vol:.2f}) -> espalhando apostas")

            # Escolher números de diferentes setores
            wheel_size = len(WHEEL_ORDER)
            step = wheel_size // spread_sector_size

            for i in range(0, wheel_size, step):
                n = WHEEL_ORDER[i]
                scores[n] = round(base_score + volatility_bonus, 4)

        elif current_vol <= low_vol_threshold:
            # Baixa volatilidade: concentrar em números quentes
            explanation_parts.append(f"Baixa volatilidade ({current_vol:.2f}) -> concentrando")

            # Encontrar números mais frequentes
            freq: Dict[int, int] = defaultdict(int)
            for n in short_segment:
                freq[n] += 1

            hot_numbers = sorted(freq.items(), key=lambda x: -x[1])[:concentrate_top_n]
            for n, count in hot_numbers:
                score = base_score + (count / len(short_segment)) * 2.0
                scores[n] = round(score, 4)

        else:
            # Volatilidade normal: estratégia balanceada
            explanation_parts.append(f"Volatilidade normal ({current_vol:.2f}) -> balanceado")

            # Mix de quentes e frios
            freq: Dict[int, int] = defaultdict(int)
            for n in long_segment:
                freq[n] += 1

            expected = len(long_segment) / 37.0

            for n in range(0, 37):
                actual = freq.get(n, 0)
                # Números levemente acima ou abaixo da média
                deviation = abs(actual - expected)
                if deviation >= expected * 0.3:
                    scores[n] = round(base_score + deviation * 0.1, 4)

        if not scores:
            return {"numbers": [], "explanation": "Volatilidade neutra, sem sugestao especifica."}

        sorted_numbers = sorted(scores.keys(), key=lambda n: (-scores[n], n))[:max_numbers]
        final_scores = {n: scores[n] for n in sorted_numbers}

        return {
            "numbers": sorted_numbers,
            "scores": final_scores,
            "explanation": " | ".join(explanation_parts),
        }

    def _eval_repeat_distance_boost(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        """
        Detecta números que repetem em intervalos regulares e
        sugere quando estão "devidos" (próximos de repetir).
        """
        if len(history) < (from_index + 50):
            return {"numbers": [], "explanation": "Historico insuficiente para analise de distancia."}

        # Parâmetros
        analysis_window = max(60, int(definition.params.get("analysis_window", 100)))
        min_repeats = max(2, int(definition.params.get("min_repeats", 2)))
        ideal_distance_min = max(8, int(definition.params.get("ideal_distance_min", 12)))
        ideal_distance_max = max(ideal_distance_min, int(definition.params.get("ideal_distance_max", 25)))
        tolerance = max(1, int(definition.params.get("tolerance", 3)))
        base_score = float(definition.params.get("base_score", 1.0))
        regularity_bonus = float(definition.params.get("regularity_bonus", 0.4))
        due_bonus = float(definition.params.get("due_bonus", 0.5))
        include_neighbors = bool(definition.params.get("include_neighbors", True))
        neighbor_score_ratio = float(definition.params.get("neighbor_score_ratio", 0.45))
        max_numbers = max(1, int(definition.max_numbers))

        # Analisar janela
        window_end = min(from_index + analysis_window, len(history))
        segment = history[from_index:window_end]

        # Para cada número, encontrar posições onde apareceu
        positions: Dict[int, List[int]] = defaultdict(list)
        for i, n in enumerate(segment):
            positions[n].append(i)

        scores: Dict[int, float] = {}
        explanation_parts: List[str] = []
        due_numbers: List[tuple[int, float]] = []

        for n, pos_list in positions.items():
            if len(pos_list) < min_repeats:
                continue

            # Calcular distâncias entre aparições
            distances = [pos_list[i+1] - pos_list[i] for i in range(len(pos_list) - 1)]

            if not distances:
                continue

            avg_distance = sum(distances) / len(distances)
            std_distance = (sum((d - avg_distance) ** 2 for d in distances) / len(distances)) ** 0.5

            # Verificar se está no intervalo ideal e é regular
            is_regular = std_distance <= tolerance
            is_ideal_interval = ideal_distance_min <= avg_distance <= ideal_distance_max

            if is_regular and is_ideal_interval:
                # Calcular se está "devido"
                last_seen = pos_list[0]  # Posição mais recente
                expected_next = last_seen + avg_distance
                current_delay = 0 - last_seen  # Quantos giros desde última aparição

                # Se está próximo ou passou do intervalo esperado
                if current_delay >= avg_distance - tolerance:
                    due_factor = min(1.0, (current_delay - avg_distance + tolerance) / (tolerance * 2))
                    score = base_score + regularity_bonus + (due_factor * due_bonus)
                    scores[n] = round(score, 4)
                    due_numbers.append((n, avg_distance))

        if due_numbers:
            due_numbers.sort(key=lambda x: -scores.get(x[0], 0))
            explanation_parts.append(f"Numeros devidos: {[f'{n}(~{d:.0f}g)' for n, d in due_numbers[:4]]}")

        if not scores:
            return {"numbers": [], "explanation": "Nenhum numero com padrao de repeticao regular."}

        # Adicionar vizinhos
        if include_neighbors:
            neighbors_to_add: Dict[int, float] = {}
            for n, score in list(scores.items()):
                for nb in self._neighbors(n):
                    if nb not in scores:
                        current = neighbors_to_add.get(nb, 0)
                        neighbors_to_add[nb] = max(current, round(score * neighbor_score_ratio, 4))
            scores.update(neighbors_to_add)

        sorted_numbers = sorted(scores.keys(), key=lambda n: (-scores[n], n))[:max_numbers]
        final_scores = {n: scores[n] for n in sorted_numbers}

        return {
            "numbers": sorted_numbers,
            "scores": final_scores,
            "explanation": " | ".join(explanation_parts) if explanation_parts else "Analise de repeticao ativa.",
        }

    def _eval_context_history_boost(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        """
        Padrão de contexto histórico:
        - Pega o número mais recente
        - Encontra as N ocorrências anteriores desse número
        - Para cada ocorrência, analisa os números que vieram antes e depois
        - Dá peso maior para números exatos, menor para vizinhos
        - Ocorrências mais recentes ganham peso extra
        """
        if len(history) < (from_index + 10):
            return {"numbers": [], "explanation": "Historico insuficiente para contexto historico."}

        # Parâmetros
        occurrences_to_find = max(2, int(definition.params.get("occurrences_to_find", 5)))
        numbers_before = max(1, int(definition.params.get("numbers_before", 3)))
        numbers_after = max(1, int(definition.params.get("numbers_after", 3)))
        base_score = float(definition.params.get("base_score", 1.0))
        neighbor_score_ratio = float(definition.params.get("neighbor_score_ratio", 0.5))
        recency_max_boost = float(definition.params.get("recency_max_boost", 1.3))
        recency_min_boost = float(definition.params.get("recency_min_boost", 0.7))
        frequency_bonus = float(definition.params.get("frequency_bonus", 0.15))
        include_neighbors = bool(definition.params.get("include_neighbors", True))
        search_window = max(100, int(definition.params.get("search_window", 500)))
        max_numbers = max(1, int(definition.max_numbers))

        # Número gatilho (o mais recente)
        trigger_number = history[from_index]

        # Encontrar as N ocorrências anteriores do número gatilho
        occurrences: List[int] = []  # Índices das ocorrências
        search_end = min(from_index + search_window, len(history))

        for i in range(from_index + 1, search_end):
            if history[i] == trigger_number:
                occurrences.append(i)
                if len(occurrences) >= occurrences_to_find:
                    break

        if len(occurrences) < 2:
            return {
                "numbers": [],
                "explanation": f"Numero {trigger_number} tem menos de 2 ocorrencias anteriores."
            }

        # Coletar números do contexto de cada ocorrência
        scores: Dict[int, float] = defaultdict(float)
        context_numbers: Dict[int, int] = defaultdict(int)  # Contagem de aparições
        total_occurrences = len(occurrences)

        for occ_idx, occ_pos in enumerate(occurrences):
            # Calcular multiplicador de recência
            # Ocorrência 0 (mais recente) = recency_max_boost
            # Última ocorrência = recency_min_boost
            if total_occurrences > 1:
                recency_factor = recency_max_boost - (
                    (recency_max_boost - recency_min_boost) * (occ_idx / (total_occurrences - 1))
                )
            else:
                recency_factor = recency_max_boost

            # Pegar números ANTES (mais antigos no histórico = índices maiores)
            for offset in range(1, numbers_before + 1):
                idx = occ_pos + offset
                if idx < len(history):
                    n = history[idx]
                    if n != trigger_number:  # Não incluir o próprio número gatilho
                        score = base_score * recency_factor
                        scores[n] += score
                        context_numbers[n] += 1

            # Pegar números DEPOIS (mais recentes no histórico = índices menores)
            for offset in range(1, numbers_after + 1):
                idx = occ_pos - offset
                if idx >= 0 and idx > from_index:
                    n = history[idx]
                    if n != trigger_number:
                        score = base_score * recency_factor
                        scores[n] += score
                        context_numbers[n] += 1

        if not scores:
            return {
                "numbers": [],
                "explanation": f"Sem contexto valido para numero {trigger_number}."
            }

        # Aplicar bônus por frequência (números que aparecem em múltiplos contextos)
        for n in scores:
            freq = context_numbers[n]
            if freq > 1:
                scores[n] += frequency_bonus * (freq - 1)

        # Adicionar vizinhos na roleta com peso reduzido
        if include_neighbors:
            neighbors_to_add: Dict[int, float] = {}
            for n, score in list(scores.items()):
                for nb in self._neighbors(n):
                    if nb not in scores and nb != trigger_number:
                        current = neighbors_to_add.get(nb, 0)
                        new_score = score * neighbor_score_ratio
                        neighbors_to_add[nb] = max(current, new_score)

            for nb, nb_score in neighbors_to_add.items():
                scores[nb] += nb_score

        # Arredondar scores
        scores = {n: round(s, 4) for n, s in scores.items()}

        # Ordenar por score e pegar top N
        sorted_numbers = sorted(scores.keys(), key=lambda n: (-scores[n], n))[:max_numbers]
        final_scores = {n: scores[n] for n in sorted_numbers}

        # Construir explicação
        top_context = sorted(context_numbers.items(), key=lambda x: -x[1])[:5]
        explanation = (
            f"Gatilho: {trigger_number} | "
            f"{total_occurrences} ocorrencias analisadas | "
            f"Top contexto: {[f'{n}({c}x)' for n, c in top_context]}"
        )

        return {
            "numbers": sorted_numbers,
            "scores": final_scores,
            "explanation": explanation,
        }

    def _eval_master_pattern_boost(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        """
        Padrao Master - Padroes Exatos:
        Busca sequencias exatas de numeros que ja ocorreram antes no historico
        e sugere o numero que veio depois dessas sequencias.
        """
        if len(history) < (from_index + 20):
            return {"numbers": [], "explanation": "Historico insuficiente para padrao Master."}

        # Parametros
        window_sizes = definition.params.get("window_sizes", [2, 3, 4])
        search_depth = int(definition.params.get("search_depth", 200))
        recent_depth = int(definition.params.get("recent_depth", 50))
        recency_decay = float(definition.params.get("recency_decay", 0.1))
        include_neighbors = bool(definition.params.get("include_neighbors", True))
        neighbor_score_ratio = float(definition.params.get("neighbor_score_ratio", 0.4))
        max_numbers = max(1, int(definition.max_numbers))

        scores: Dict[int, float] = defaultdict(float)
        patterns_found = 0
        hist = history[from_index:]

        for window_size in window_sizes:
            if len(hist) < window_size + 1:
                continue

            # Buscar padroes no historico recente
            for i in range(min(recent_depth, len(hist) - window_size)):
                current_pattern = tuple(hist[i:i + window_size])

                # Procurar esse padrao no resto do historico
                for j in range(i + window_size, min(search_depth, len(hist) - 1)):
                    comparison_pattern = tuple(hist[j:j + window_size])

                    if current_pattern == comparison_pattern:
                        if j + window_size < len(hist):
                            next_number = hist[j + window_size]
                            # Peso maior para janelas maiores e padroes mais recentes
                            weight = window_size * (1.0 / (1 + i * recency_decay))
                            scores[next_number] += weight
                            patterns_found += 1

        if not scores:
            return {
                "numbers": [],
                "explanation": "Nenhum padrao exato encontrado no historico."
            }

        # Adicionar vizinhos
        if include_neighbors:
            neighbors_to_add: Dict[int, float] = {}
            for n, score in list(scores.items()):
                for nb in self._neighbors(n):
                    if nb not in scores:
                        current = neighbors_to_add.get(nb, 0)
                        new_score = score * neighbor_score_ratio
                        neighbors_to_add[nb] = max(current, new_score)

            for nb, nb_score in neighbors_to_add.items():
                scores[nb] += nb_score

        # Ordenar e limitar
        sorted_numbers = sorted(scores.keys(), key=lambda n: (-scores[n], n))[:max_numbers]
        final_scores = {n: round(scores[n], 4) for n in sorted_numbers}

        return {
            "numbers": sorted_numbers,
            "scores": final_scores,
            "explanation": f"Master ativo: {patterns_found} padroes exatos encontrados.",
        }

    def _eval_estelar_equivalence_boost(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        """
        Padrao Estelar - Equivalencias:
        Analisa espelhos, vizinhos, terminal, soma de digitos e retornos frequentes.
        """
        if len(history) < (from_index + 10):
            return {"numbers": [], "explanation": "Historico insuficiente para padrao Estelar."}

        # Espelhos fixos
        MIRRORS = {
            1: 10, 10: 1, 2: 20, 20: 2, 3: 30, 30: 3,
            6: 9, 9: 6, 16: 19, 19: 16, 26: 29, 29: 26,
            13: 31, 31: 13, 12: 21, 21: 12, 32: 23, 23: 32
        }

        # Parametros
        context_size = int(definition.params.get("context_size", 30))
        mirror_weight = float(definition.params.get("mirror_weight", 10))
        neighbor_weight = float(definition.params.get("neighbor_weight", 7))
        terminal_weight = float(definition.params.get("terminal_weight", 5))
        sum_weight = float(definition.params.get("sum_weight", 5))
        return_weight = float(definition.params.get("return_weight", 8))
        min_returns = int(definition.params.get("min_returns", 2))
        include_neighbors = bool(definition.params.get("include_neighbors", True))
        neighbor_score_ratio = float(definition.params.get("neighbor_score_ratio", 0.45))
        max_numbers = max(1, int(definition.max_numbers))

        scores: Dict[int, float] = defaultdict(float)
        hist = history[from_index:]
        ctx = hist[:context_size]
        recent = ctx[0] if ctx else 0

        # 1. ESPELHOS DO CONTEXTO
        mirrors_found = set()
        for n in ctx[:20]:
            if n in MIRRORS:
                mirrors_found.add(MIRRORS[n])

        for mirror in mirrors_found:
            scores[mirror] += mirror_weight

        # 2. RETORNOS FREQUENTES (numeros que apareceram 2+ vezes)
        freq: Dict[int, int] = {}
        for n in ctx:
            freq[n] = freq.get(n, 0) + 1

        returns = sorted(
            [(n, f) for n, f in freq.items() if f >= min_returns],
            key=lambda x: x[1],
            reverse=True
        )

        for i, (num, frequency) in enumerate(returns):
            points = max(return_weight - i, 1) + (frequency - 1)
            scores[num] += points

        # 3. FAMILIA DO TERMINAL (mesmo ultimo digito)
        terminal = recent % 10
        for i in range(terminal, 37, 10):
            if i >= 0 and i != recent:
                scores[i] += terminal_weight

        # 4. NUMEROS COM MESMA SOMA DE DIGITOS
        def digit_sum(n: int) -> int:
            return (n // 10) + (n % 10)

        recent_sum = digit_sum(recent)
        for i in range(1, 37):
            if digit_sum(i) == recent_sum and i not in ctx[:20]:
                scores[i] += sum_weight

        # 5. VIZINHOS DO ULTIMO
        for nb in self._neighbors(recent):
            scores[nb] += neighbor_weight

        # 6. ESPELHO DIRETO DO ULTIMO (peso extra)
        if recent in MIRRORS:
            scores[MIRRORS[recent]] += mirror_weight * 0.8

        # Adicionar vizinhos extras se configurado
        if include_neighbors:
            neighbors_to_add: Dict[int, float] = {}
            for n, score in list(scores.items()):
                for nb in self._neighbors(n):
                    if nb not in scores:
                        current = neighbors_to_add.get(nb, 0)
                        new_score = score * neighbor_score_ratio
                        neighbors_to_add[nb] = max(current, new_score)

            for nb, nb_score in neighbors_to_add.items():
                scores[nb] += nb_score

        # Ordenar e limitar
        sorted_numbers = sorted(scores.keys(), key=lambda n: (-scores[n], n))[:max_numbers]
        final_scores = {n: round(scores[n], 4) for n in sorted_numbers}

        return {
            "numbers": sorted_numbers,
            "scores": final_scores,
            "explanation": f"Estelar ativo: espelhos={len(mirrors_found)}, retornos={len(returns)}, terminal={terminal}.",
        }

    def _eval_chain_behavior_boost(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        """
        Padrao Chain - Cadeias Comportamentais:
        Detecta puxadas recorrentes (X puxa Y duas ou mais vezes) e numeros faltantes.
        """
        if len(history) < (from_index + 20):
            return {"numbers": [], "explanation": "Historico insuficiente para padrao Chain."}

        # Espelhos fixos
        MIRRORS = {
            1: 10, 10: 1, 2: 20, 20: 2, 3: 30, 30: 3,
            6: 9, 9: 6, 16: 19, 19: 16, 26: 29, 29: 26,
            13: 31, 31: 13, 12: 21, 21: 12, 32: 23, 23: 32
        }

        # Parametros
        chain_search_depth = int(definition.params.get("chain_search_depth", 150))
        min_chain_occurrences = int(definition.params.get("min_chain_occurrences", 2))
        recent_context = int(definition.params.get("recent_context", 5))
        chain_weight = float(definition.params.get("chain_weight", 4))
        missing_neighbor_weight = float(definition.params.get("missing_neighbor_weight", 10))
        missing_mirror_weight = float(definition.params.get("missing_mirror_weight", 6))
        include_neighbors = bool(definition.params.get("include_neighbors", True))
        neighbor_score_ratio = float(definition.params.get("neighbor_score_ratio", 0.4))
        max_numbers = max(1, int(definition.max_numbers))

        scores: Dict[int, float] = defaultdict(float)
        faltantes: List[int] = []
        hist = history[from_index:]

        # 1. DETECTAR CADEIAS RECORRENTES (X -> Y acontece 2+ vezes)
        chains: Dict[str, int] = {}
        search_limit = min(chain_search_depth, len(hist) - 1)

        for i in range(search_limit):
            key = f"{hist[i]}->{hist[i + 1]}"
            chains[key] = chains.get(key, 0) + 1

        strong_chains = {k: v for k, v in chains.items() if v >= min_chain_occurrences}

        # 2. ANALISAR ULTIMOS N NUMEROS
        last_n = hist[:recent_context]

        # Verificar cadeias ativas
        for i in range(len(last_n) - 1):
            key = f"{last_n[i]}->{last_n[i + 1]}"

            if key in strong_chains:
                # Procurar o que normalmente vem depois
                for j in range(len(hist) - 2):
                    if hist[j] == last_n[i] and hist[j + 1] == last_n[i + 1]:
                        if j + 2 < len(hist):
                            next_num = hist[j + 2]
                            weight = strong_chains[key] * chain_weight
                            scores[next_num] += weight
                            if next_num not in faltantes:
                                faltantes.append(next_num)

        # 3. DETECTAR FALTANTES POR VIZINHANCA
        for num in range(37):
            left_nb, right_nb = self._neighbors(num) if num in WHEEL_ORDER else (None, None)
            if left_nb is None:
                continue

            # Verificar se vizinhos aparecem mas o numero nao
            if left_nb in last_n and right_nb in last_n:
                if num not in hist[:15]:
                    scores[num] += missing_neighbor_weight
                    if num not in faltantes:
                        faltantes.append(num)

        # 4. ESPELHOS QUE FALTAM
        for num in last_n[:3]:
            if num in MIRRORS:
                mirror = MIRRORS[num]
                if mirror not in hist[:20]:
                    scores[mirror] += missing_mirror_weight
                    if mirror not in faltantes:
                        faltantes.append(mirror)

        if not scores:
            return {
                "numbers": [],
                "explanation": "Nenhuma cadeia ou faltante detectado."
            }

        # Adicionar vizinhos
        if include_neighbors:
            neighbors_to_add: Dict[int, float] = {}
            for n, score in list(scores.items()):
                for nb in self._neighbors(n):
                    if nb not in scores:
                        current = neighbors_to_add.get(nb, 0)
                        new_score = score * neighbor_score_ratio
                        neighbors_to_add[nb] = max(current, new_score)

            for nb, nb_score in neighbors_to_add.items():
                scores[nb] += nb_score

        # Ordenar e limitar
        sorted_numbers = sorted(scores.keys(), key=lambda n: (-scores[n], n))[:max_numbers]
        final_scores = {n: round(scores[n], 4) for n in sorted_numbers}

        return {
            "numbers": sorted_numbers,
            "scores": final_scores,
            "explanation": f"Chain ativo: {len(strong_chains)} cadeias fortes, {len(faltantes)} faltantes.",
        }

    def _eval_cavalos_faltantes_boost(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        """
        Padrao Cavalos Faltantes:
        Detecta quando 2 dos 3 grupos de cavalos aparecem e sugere o terceiro.
        Grupos: 147 (terminais 1,4,7), 258 (terminais 2,5,8), 0369 (terminais 0,3,6,9)
        """
        if len(history) < (from_index + 10):
            return {"numbers": [], "explanation": "Historico insuficiente para Cavalos Faltantes."}

        # Definicao dos cavalos
        CAVALOS = {
            "147": [1, 11, 21, 31, 4, 14, 24, 34, 7, 17, 27],
            "258": [2, 12, 22, 32, 5, 15, 25, 35, 8, 18, 28],
            "0369": [0, 10, 20, 30, 3, 13, 23, 33, 6, 16, 26, 36, 9, 19, 29]
        }

        TERMINAL_GROUPS = [
            {1, 4, 7},
            {2, 5, 8},
            {0, 3, 6},
            {3, 6, 9},
        ]

        include_neighbors = bool(definition.params.get("include_neighbors", True))
        neighbor_score_ratio = float(definition.params.get("neighbor_score_ratio", 0.4))
        max_numbers = max(1, int(definition.max_numbers))

        hist = history[from_index:]
        if len(hist) < 4:
            return {"numbers": [], "explanation": "Historico insuficiente."}

        gatilho = hist[0]
        scores: Dict[int, float] = defaultdict(float)

        # Encontrar ocorrencias anteriores do gatilho
        indices = []
        for i in range(1, min(200, len(hist))):
            if hist[i] == gatilho:
                indices.append(i)
                if len(indices) >= 4:
                    break

        if len(indices) < 2:
            return {"numbers": [], "explanation": "Poucas ocorrencias do gatilho."}

        # Verificar os cavalos antes de cada ocorrencia
        cavalos_antes = []
        for idx in indices[:2]:
            if idx > 0:
                num_antes = hist[idx - 1]
                terminal = num_antes % 10
                cavalos_antes.append(terminal)

        if len(cavalos_antes) < 2:
            return {"numbers": [], "explanation": "Sem cavalos suficientes."}

        t1, t2 = cavalos_antes[0], cavalos_antes[1]

        if t1 == t2:
            return {"numbers": [], "explanation": "Terminais iguais, sem cavalo faltante."}

        # Encontrar cavalo faltante
        cavalo_faltante = None
        for group in TERMINAL_GROUPS:
            if t1 in group and t2 in group:
                faltantes = group - {t1, t2}
                if faltantes:
                    cavalo_faltante = next(iter(faltantes))
                    break

        if cavalo_faltante is None:
            return {"numbers": [], "explanation": "Nenhum cavalo faltante detectado."}

        # Verificar se cavalo faltante ja apareceu recentemente
        if cavalo_faltante in [n % 10 for n in hist[1:4]]:
            return {"numbers": [], "explanation": "Cavalo faltante ja apareceu."}

        # Montar aposta baseada no cavalo faltante
        if cavalo_faltante in [0, 3, 6, 9]:
            bet_numbers = CAVALOS["0369"]
        elif cavalo_faltante in [1, 4, 7]:
            bet_numbers = CAVALOS["147"]
        else:
            bet_numbers = CAVALOS["258"]

        for n in bet_numbers:
            scores[n] = 10.0

        # Adicionar vizinhos
        if include_neighbors:
            for n in list(scores.keys()):
                for nb in self._neighbors(n):
                    if nb not in scores:
                        scores[nb] = scores[n] * neighbor_score_ratio

        sorted_numbers = sorted(scores.keys(), key=lambda n: (-scores[n], n))[:max_numbers]
        final_scores = {n: round(scores[n], 4) for n in sorted_numbers}

        return {
            "numbers": sorted_numbers,
            "scores": final_scores,
            "explanation": f"Cavalo faltante: terminal {cavalo_faltante}. Gatilho: {gatilho}.",
        }

    def _eval_gemeos_boost(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        """
        Padrao Gemeos:
        Quando sai 11, 22 ou 33, sugere numeros especificos.
        """
        if len(history) < (from_index + 3):
            return {"numbers": [], "explanation": "Historico insuficiente para Gemeos."}

        gemeos = definition.params.get("gemeos_numbers", [11, 22, 33])
        bet_numbers = definition.params.get("bet_numbers", [0, 18, 22, 9, 1, 33, 16, 11, 30, 36])
        include_neighbors = bool(definition.params.get("include_neighbors", True))
        neighbor_score_ratio = float(definition.params.get("neighbor_score_ratio", 0.35))
        max_numbers = max(1, int(definition.max_numbers))

        hist = history[from_index:]
        ultimo = hist[0]
        penultimo = hist[1] if len(hist) > 1 else None

        # Ativa quando o ultimo numero e gemeo e o penultimo nao e
        if ultimo not in gemeos:
            return {"numbers": [], "explanation": "Ultimo numero nao e gemeo."}

        if penultimo in gemeos:
            return {"numbers": [], "explanation": "Penultimo tambem e gemeo, ignorando."}

        scores: Dict[int, float] = defaultdict(float)

        for n in bet_numbers:
            scores[n] = 10.0

        # Adicionar vizinhos
        if include_neighbors:
            for n in list(scores.keys()):
                for nb in self._neighbors(n):
                    if nb not in scores:
                        scores[nb] = scores[n] * neighbor_score_ratio

        sorted_numbers = sorted(scores.keys(), key=lambda n: (-scores[n], n))[:max_numbers]
        final_scores = {n: round(scores[n], 4) for n in sorted_numbers}

        return {
            "numbers": sorted_numbers,
            "scores": final_scores,
            "explanation": f"Gemeo detectado: {ultimo}. Alvos: {gemeos}.",
        }

    def _eval_terminais_iguais_boost(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        """
        Padrao Terminais Iguais:
        Quando dois numeros consecutivos tem o mesmo terminal, sugere o terceiro terminal.
        """
        if len(history) < (from_index + 3):
            return {"numbers": [], "explanation": "Historico insuficiente para Terminais Iguais."}

        excluded_terminals = definition.params.get("excluded_terminals", [7, 8])
        include_neighbors = bool(definition.params.get("include_neighbors", True))
        neighbor_score_ratio = float(definition.params.get("neighbor_score_ratio", 0.4))
        max_numbers = max(1, int(definition.max_numbers))

        hist = history[from_index:]
        n0, n1, n2 = hist[0], hist[1], hist[2]

        t0 = n0 % 10
        t1 = n1 % 10
        t2 = n2 % 10

        # Verifica se os dois primeiros tem o mesmo terminal
        if t0 != t1:
            return {"numbers": [], "explanation": "Terminais diferentes."}

        # Verifica se sao numeros diferentes
        if n0 == n1:
            return {"numbers": [], "explanation": "Numeros iguais."}

        # Verifica se terceiro terminal e diferente
        if t2 == t0:
            return {"numbers": [], "explanation": "Terceiro terminal igual."}

        # Verifica se e zero
        if n2 == 0:
            return {"numbers": [], "explanation": "Terceiro numero e zero."}

        # Verifica terminais excluidos
        if t2 in excluded_terminals:
            return {"numbers": [], "explanation": f"Terminal {t2} excluido."}

        scores: Dict[int, float] = defaultdict(float)

        # Numeros com terminal t2
        terminais_t2 = [i for i in range(37) if i % 10 == t2]

        # Figuras (soma dos digitos)
        def get_figure(terminal: int) -> List[int]:
            figures = []
            for i in range(1, 37):
                soma = (i // 10) + (i % 10)
                if soma == terminal:
                    figures.append(i)
            return figures

        figuras = get_figure(t2)

        for n in terminais_t2:
            scores[n] = 10.0

        for n in figuras:
            scores[n] = scores.get(n, 0) + 5.0

        # Adicionar 0 sempre
        scores[0] = 8.0

        # Casos especiais
        if t2 == 9:
            for n in [i for i in range(37) if i % 10 == 6]:
                scores[n] = scores.get(n, 0) + 3.0

        if t2 == 4:
            scores[1] = scores.get(1, 0) + 3.0
            scores[33] = scores.get(33, 0) + 3.0

        # Adicionar vizinhos
        if include_neighbors:
            for n in list(scores.keys()):
                for nb in self._neighbors(n):
                    if nb not in scores:
                        scores[nb] = scores[n] * neighbor_score_ratio

        sorted_numbers = sorted(scores.keys(), key=lambda n: (-scores[n], n))[:max_numbers]
        final_scores = {n: round(scores[n], 4) for n in sorted_numbers}

        return {
            "numbers": sorted_numbers,
            "scores": final_scores,
            "explanation": f"Terminais iguais: {t0}. Terceiro terminal: {t2}.",
        }

    def _eval_puxou_cavalo_boost(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        """
        Padrao Puxou Cavalo:
        Quando sai numero de 0 a 9, aposta no cavalo inteiro correspondente.
        """
        if len(history) < (from_index + 10):
            return {"numbers": [], "explanation": "Historico insuficiente para Puxou Cavalo."}

        CAVALOS = {
            "147": [0, 1, 11, 21, 31, 4, 14, 24, 34, 7, 17, 27],
            "258": [0, 2, 12, 22, 32, 5, 15, 25, 35, 8, 18, 28],
            "0369": [0, 10, 20, 30, 3, 13, 23, 33, 6, 16, 26, 36, 9, 19, 29]
        }

        MIRRORS = {
            1: 10, 10: 1, 2: 20, 20: 2, 3: 30, 30: 3,
            6: 9, 9: 6, 16: 19, 19: 16, 26: 29, 29: 26,
            13: 31, 31: 13, 12: 21, 21: 12, 32: 23, 23: 32
        }

        min_distance = int(definition.params.get("min_distance", 5))
        check_window = int(definition.params.get("check_window", 3))
        include_mirror = bool(definition.params.get("include_mirror", True))
        include_neighbors = bool(definition.params.get("include_neighbors", True))
        neighbor_score_ratio = float(definition.params.get("neighbor_score_ratio", 0.35))
        max_numbers = max(1, int(definition.max_numbers))

        hist = history[from_index:]
        base = hist[0]

        # Verifica se base esta entre 0 e 9
        if base < 0 or base > 9:
            return {"numbers": [], "explanation": f"Numero {base} fora do range 0-9."}

        # Verifica se nao e consecutivo
        if len(hist) > 1:
            diff = abs(base - hist[1])
            if diff == 1 or (base == 0 and hist[1] == 36) or (base == 36 and hist[1] == 0):
                return {"numbers": [], "explanation": "Numeros consecutivos."}

        # Verifica se penultimo esta entre 1-9
        if len(hist) > 1 and 1 <= hist[1] <= 9:
            return {"numbers": [], "explanation": "Penultimo entre 1-9."}

        # Determina o cavalo
        terminal = base % 10
        if terminal in [1, 4, 7]:
            cavalo_key = "147"
        elif terminal in [2, 5, 8]:
            cavalo_key = "258"
        else:
            cavalo_key = "0369"

        # Encontra proxima ocorrencia do base
        indice = None
        for i in range(1, min(100, len(hist))):
            if hist[i] == base:
                indice = i
                break

        if indice is None or indice <= min_distance:
            return {"numbers": [], "explanation": "Muito proximo ou nao encontrado."}

        # Verifica se pagou na ocorrencia anterior
        window_check = hist[indice - check_window:indice]
        cavalo_nums = set(CAVALOS[cavalo_key])
        if cavalo_nums & set(window_check):
            return {"numbers": [], "explanation": "Ja pagou na ocorrencia anterior."}

        scores: Dict[int, float] = defaultdict(float)

        for n in CAVALOS[cavalo_key]:
            scores[n] = 10.0

        # Adiciona espelho
        if include_mirror and base in MIRRORS:
            mirror = MIRRORS[base]
            scores[mirror] = scores.get(mirror, 0) + 5.0

        # Adiciona vizinhos
        scores[base - 1] = scores.get(base - 1, 0) + 3.0 if base > 0 else 0
        scores[base + 1] = scores.get(base + 1, 0) + 3.0 if base < 36 else 0

        if include_neighbors:
            for n in list(scores.keys()):
                for nb in self._neighbors(n):
                    if nb not in scores:
                        scores[nb] = scores[n] * neighbor_score_ratio

        sorted_numbers = sorted(scores.keys(), key=lambda n: (-scores[n], n))[:max_numbers]
        final_scores = {n: round(scores[n], 4) for n in sorted_numbers}

        return {
            "numbers": sorted_numbers,
            "scores": final_scores,
            "explanation": f"Puxou cavalo {cavalo_key}. Base: {base}.",
        }

    def _eval_sequencia_pulada_0369_boost(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        """
        Padrao Sequencia Pulada 0369:
        Detecta sequencia pulada (ex: 5-7 pulou 6) e aposta no cavalo 0369.
        """
        if len(history) < (from_index + 3):
            return {"numbers": [], "explanation": "Historico insuficiente para Sequencia Pulada."}

        cavalo_0369 = definition.params.get(
            "cavalo_0369",
            [0, 3, 6, 9, 10, 13, 16, 19, 20, 23, 26, 29, 30, 33, 36]
        )
        max_numbers = max(1, int(definition.max_numbers))

        hist = history[from_index:]
        p1, p2 = hist[1], hist[2]

        # Verifica se e sequencia pulada
        def is_skipped_sequence(a: int, b: int) -> bool:
            diff = abs(a - b)
            return diff == 2

        if not is_skipped_sequence(p1, p2):
            return {"numbers": [], "explanation": "Nao e sequencia pulada."}

        scores: Dict[int, float] = defaultdict(float)

        for n in cavalo_0369:
            scores[n] = 10.0

        sorted_numbers = sorted(scores.keys(), key=lambda n: (-scores[n], n))[:max_numbers]
        final_scores = {n: round(scores[n], 4) for n in sorted_numbers}

        return {
            "numbers": sorted_numbers,
            "scores": final_scores,
            "explanation": f"Sequencia pulada detectada: {p1}-{p2}. Aposta no cavalo 0369.",
        }

    def _eval_alinhamento_boost(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        """
        Padrão Alinhamento (Triangulação):
        Busca ocorrências de números e constrói score baseado no que vem após.
        """
        num_ocorrencias = definition.params.get("num_ocorrencias", 3)
        nums_para_tras = definition.params.get("nums_para_tras", 40)
        nums_apos_ocorrencia = definition.params.get("nums_apos_ocorrencia", 3)
        aplicar_decaimento = definition.params.get("aplicar_decaimento", True)
        peso_vizinhos = definition.params.get("peso_vizinhos", 0.9)
        max_numbers = max(1, int(definition.max_numbers))

        hist = history[from_index:]
        if len(hist) < nums_para_tras + 10:
            return {"numbers": [], "explanation": "Histórico insuficiente para Alinhamento."}

        scores: Dict[int, float] = defaultdict(float)
        numeros_pagos: Set[int] = set()

        # Para cada número no window
        for idx in range(1, min(nums_para_tras + 1, len(hist))):
            trigger = hist[idx]
            if trigger == 0:
                continue

            # Buscar ocorrências do trigger
            ocorrencias = []
            last_index = idx
            for _ in range(num_ocorrencias):
                found_idx = None
                for i in range(last_index + 1, len(hist)):
                    if hist[i] == trigger:
                        found_idx = i
                        break
                if found_idx is None:
                    break
                ocorrencias.append(found_idx)
                last_index = found_idx

            if len(ocorrencias) < num_ocorrencias:
                continue

            # Pegar números após cada ocorrência
            for occ_idx in ocorrencias:
                if occ_idx + nums_apos_ocorrencia >= len(hist):
                    continue
                for i in range(1, nums_apos_ocorrencia + 1):
                    if occ_idx + i < len(hist):
                        num = hist[occ_idx + i]
                        if num is not None:
                            scores[num] += 1.0
                            # Vizinhos
                            if peso_vizinhos > 0:
                                for viz in self._neighbors(num):
                                    scores[viz] += peso_vizinhos

                if aplicar_decaimento and occ_idx < len(hist):
                    numeros_pagos.add(hist[occ_idx])

            # Números após o trigger original
            for i in range(1, nums_apos_ocorrencia + 1):
                if idx + i < len(hist):
                    num = hist[idx + i]
                    if num is not None:
                        scores[num] += 1.0
                        if peso_vizinhos > 0:
                            for viz in self._neighbors(num):
                                scores[viz] += peso_vizinhos

            if aplicar_decaimento:
                numeros_pagos.add(trigger)

        # Aplicar decaimento
        if aplicar_decaimento:
            for num_pago in numeros_pagos:
                for viz in self._neighbors(num_pago):
                    scores[viz] = max(0, scores[viz] - 0.6)

        # Remover scores zero ou negativos
        scores = {k: v for k, v in scores.items() if v > 0}

        if not scores:
            return {"numbers": [], "explanation": "Nenhum alinhamento encontrado."}

        sorted_numbers = sorted(scores.keys(), key=lambda n: (-scores[n], n))[:max_numbers]
        final_scores = {n: round(scores[n], 4) for n in sorted_numbers}

        return {
            "numbers": sorted_numbers,
            "scores": final_scores,
            "explanation": f"Triangulação: {len(sorted_numbers)} números encontrados.",
        }

    def _eval_alinhamento_final_boost(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        """
        Padrão Alinhamento Final:
        Usa posição 8 como trigger e busca alinhamentos.
        """
        MIRRORS = {
            1: 10, 10: 1, 2: 20, 20: 2, 3: 30, 30: 3,
            6: 9, 9: 6, 16: 19, 19: 16, 26: 29, 29: 26,
            13: 31, 31: 13, 12: 21, 21: 12, 32: 23, 23: 32
        }

        trigger_position = definition.params.get("trigger_position", 8)
        max_indice2 = definition.params.get("max_indice2", 200)
        include_neighbors = definition.params.get("include_neighbors", True)
        include_mirrors = definition.params.get("include_mirrors", True)
        max_numbers = max(1, int(definition.max_numbers))

        hist = history[from_index:]
        if len(hist) < 50:
            return {"numbers": [], "explanation": "Histórico insuficiente para Alinhamento Final."}

        if trigger_position >= len(hist):
            return {"numbers": [], "explanation": "Posição de trigger fora do histórico."}

        p8 = hist[trigger_position]

        # Verificar se pagou antes
        if p8 in hist[0:trigger_position - 1]:
            return {"numbers": [], "explanation": "Trigger já pagou antes."}

        # Buscar índice1 (primeira ocorrência após trigger_position)
        indice1 = None
        for i in range(trigger_position + 1, len(hist)):
            if hist[i] == p8:
                indice1 = i
                break

        if indice1 is None:
            return {"numbers": [], "explanation": "Índice 1 não encontrado."}

        # Buscar índice2
        indice2 = None
        for i in range(indice1 + 1, len(hist)):
            if hist[i] == p8:
                indice2 = i
                break

        if indice2 is None or indice2 > max_indice2:
            return {"numbers": [], "explanation": "Índice 2 não encontrado ou muito distante."}

        # Alvo é o número após índice2
        if indice2 + 1 >= len(hist):
            return {"numbers": [], "explanation": "Sem alvo após índice2."}

        alvo = hist[indice2 + 1]
        if alvo == 0:
            return {"numbers": [], "explanation": "Alvo é zero."}

        # Construir aposta
        scores: Dict[int, float] = defaultdict(float)
        scores[alvo] = 10.0
        scores[p8] = 8.0

        if include_neighbors:
            for viz in self._neighbors(alvo):
                scores[viz] += 5.0

        if include_mirrors and alvo in MIRRORS:
            espelho = MIRRORS[alvo]
            scores[espelho] += 4.0
            # Vizinhos do espelho
            for viz in self._neighbors(espelho):
                scores[viz] += 2.0

        sorted_numbers = sorted(scores.keys(), key=lambda n: (-scores[n], n))[:max_numbers]
        final_scores = {n: round(scores[n], 4) for n in sorted_numbers}

        return {
            "numbers": sorted_numbers,
            "scores": final_scores,
            "explanation": f"Alinhamento Final: trigger={p8}, alvo={alvo}.",
        }

    def _eval_alinhamento_total_boost(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        """
        Padrão Alinhamento Total:
        Usa posição 0 como base e busca alinhamentos nas ocorrências.
        """
        MIRRORS = {
            1: 10, 10: 1, 2: 20, 20: 2, 3: 30, 30: 3,
            6: 9, 9: 6, 16: 19, 19: 16, 26: 29, 29: 26,
            13: 31, 31: 13, 12: 21, 21: 12, 32: 23, 23: 32
        }

        sequence_size = definition.params.get("sequence_size", 4)
        include_neighbors = definition.params.get("include_neighbors", True)
        include_mirrors = definition.params.get("include_mirrors", True)
        max_bet_size = definition.params.get("max_bet_size", 20)
        max_numbers = max(1, int(definition.max_numbers))

        hist = history[from_index:]
        if len(hist) < 50:
            return {"numbers": [], "explanation": "Histórico insuficiente para Alinhamento Total."}

        p0 = hist[0]

        # Buscar índice1
        indice1 = None
        for i in range(2, len(hist)):
            if hist[i] == p0:
                indice1 = i
                break

        if indice1 is None:
            return {"numbers": [], "explanation": "Índice 1 não encontrado."}

        # Buscar índice2
        indice2 = None
        for i in range(indice1 + 1, len(hist)):
            if hist[i] == p0:
                indice2 = i
                break

        if indice2 is None:
            return {"numbers": [], "explanation": "Índice 2 não encontrado."}

        # Pegar sequências após cada índice
        bet1 = hist[indice1:indice1 + sequence_size] if indice1 + sequence_size <= len(hist) else []
        bet2 = hist[indice2:indice2 + sequence_size] if indice2 + sequence_size <= len(hist) else []

        scores: Dict[int, float] = defaultdict(float)

        for n in bet1:
            scores[n] += 5.0
        for n in bet2:
            scores[n] += 5.0

        # Sempre incluir 0
        scores[0] += 3.0

        if include_neighbors:
            for n in list(scores.keys()):
                for viz in self._neighbors(n):
                    scores[viz] += 2.0

        if include_mirrors:
            for n in list(scores.keys()):
                if n in MIRRORS:
                    scores[MIRRORS[n]] += 1.5

        if len(scores) > max_bet_size:
            sorted_all = sorted(scores.keys(), key=lambda n: (-scores[n], n))
            scores = {n: scores[n] for n in sorted_all[:max_bet_size]}

        sorted_numbers = sorted(scores.keys(), key=lambda n: (-scores[n], n))[:max_numbers]
        final_scores = {n: round(scores[n], 4) for n in sorted_numbers}

        return {
            "numbers": sorted_numbers,
            "scores": final_scores,
            "explanation": f"Alinhamento Total: base={p0}, idx1={indice1}, idx2={indice2}.",
        }

    def _eval_numero_quente_boost(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        """
        Padrão Número Quente:
        Análise de proximidade com pesos para números quentes.
        """
        peso_principal = definition.params.get("peso_principal", 3.5)
        peso_vizinhos = definition.params.get("peso_vizinhos", 1.4)
        peso_vizinhos1 = definition.params.get("peso_vizinhos1", 0.8)
        peso_duzia = definition.params.get("peso_duzia", 0.5)
        peso_puxada = definition.params.get("peso_puxada", 2.0)
        qtd_puxada = definition.params.get("qtd_puxada", 10)
        decaimento = definition.params.get("decaimento", 0.5)
        window_size = definition.params.get("window_size", 40)
        top_ranking = definition.params.get("top_ranking", 12)
        max_numbers = max(1, int(definition.max_numbers))

        hist = history[from_index:]
        if len(hist) < 50:
            return {"numbers": [], "explanation": "Histórico insuficiente para Número Quente."}

        scores: Dict[int, float] = defaultdict(float)

        # Analisar window_size números
        for idx, number in enumerate(hist[:window_size]):
            # Peso decai com a posição
            decay_factor = max(0.1, 1.0 - (idx * decaimento / window_size))

            # Peso principal
            scores[number] += peso_principal * decay_factor

            # Vizinhos diretos (1 casa)
            neighbors_1 = self._neighbors(number)
            for viz in neighbors_1:
                scores[viz] += peso_vizinhos * decay_factor

            # Vizinhos secundários (2 casas) - vizinhos dos vizinhos
            neighbors_2 = set()
            for n1 in neighbors_1:
                for n2 in self._neighbors(n1):
                    if n2 != number and n2 not in neighbors_1:
                        neighbors_2.add(n2)
            for viz in neighbors_2:
                scores[viz] += peso_vizinhos1 * decay_factor

            # Peso da dúzia
            for dozen_name, dozen_numbers in DOZEN_MAP.items():
                if number in dozen_numbers:
                    for dn in dozen_numbers:
                        scores[dn] += peso_duzia * decay_factor * 0.1

        # Análise de puxada (números que aparecem após outros)
        for i in range(min(qtd_puxada, len(hist) - 1)):
            if i + 1 < len(hist):
                puxou = hist[i]
                puxado = hist[i + 1]
                scores[puxado] += peso_puxada * (1.0 - i / qtd_puxada)

        # Pegar top ranking
        sorted_numbers = sorted(scores.keys(), key=lambda n: (-scores[n], n))[:top_ranking]
        sorted_numbers = sorted_numbers[:max_numbers]
        final_scores = {n: round(scores[n], 4) for n in sorted_numbers}

        return {
            "numbers": sorted_numbers,
            "scores": final_scores,
            "explanation": f"Número Quente: {len(sorted_numbers)} números mais quentes.",
        }

    def _eval_patchoko_rep_boost(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        """
        Padrão Patchoko Repetição:
        Quando p0 == p1 (número repetiu), aposta no cavalo 0369.
        """
        cavalo_0369 = definition.params.get(
            "cavalo_0369",
            [0, 3, 6, 9, 10, 13, 16, 19, 20, 23, 26, 29, 30, 33, 36]
        )
        max_numbers = max(1, int(definition.max_numbers))

        hist = history[from_index:]
        if len(hist) < 2:
            return {"numbers": [], "explanation": "Histórico insuficiente para Patchoko Rep."}

        p0, p1 = hist[0], hist[1]

        if p0 != p1:
            return {"numbers": [], "explanation": "Não houve repetição (p0 != p1)."}

        scores: Dict[int, float] = defaultdict(float)
        for n in cavalo_0369:
            scores[n] = 10.0

        sorted_numbers = sorted(scores.keys(), key=lambda n: (-scores[n], n))[:max_numbers]
        final_scores = {n: round(scores[n], 4) for n in sorted_numbers}

        return {
            "numbers": sorted_numbers,
            "scores": final_scores,
            "explanation": f"Patchoko Repetição: {p0} repetiu. Aposta no cavalo 0369.",
        }

    def _eval_patchoko_seq_boost(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        """
        Padrão Patchoko Sequência:
        Quando p1 e p2 são consecutivos, aposta no cavalo 0369.
        """
        cavalo_0369 = definition.params.get(
            "cavalo_0369",
            [0, 3, 6, 9, 10, 13, 16, 19, 20, 23, 26, 29, 30, 33, 36]
        )
        max_numbers = max(1, int(definition.max_numbers))

        hist = history[from_index:]
        if len(hist) < 3:
            return {"numbers": [], "explanation": "Histórico insuficiente para Patchoko Seq."}

        p1, p2 = hist[1], hist[2]

        def is_consecutive(a: int, b: int) -> bool:
            return abs(a - b) == 1

        if not is_consecutive(p1, p2):
            return {"numbers": [], "explanation": "Não há sequência consecutiva (p1, p2)."}

        scores: Dict[int, float] = defaultdict(float)
        for n in cavalo_0369:
            scores[n] = 10.0

        sorted_numbers = sorted(scores.keys(), key=lambda n: (-scores[n], n))[:max_numbers]
        final_scores = {n: round(scores[n], 4) for n in sorted_numbers}

        return {
            "numbers": sorted_numbers,
            "scores": final_scores,
            "explanation": f"Patchoko Sequência: {p1}-{p2} consecutivos. Aposta no cavalo 0369.",
        }

    def _eval_blackhorse_boost(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        """
        Padrao Black Horse (Math Absolu):

        Gatilho: numero mais recente = 10, 20 ou 30
        Logica: Pega o numero anterior (n_prev) e subtrai 36 repetidamente
        ate encontrar um terminal valido (1,4,7 ou 2,5,8).

        Cancelamentos:
        - n_prev = 0
        - n_prev = gatilho
        - Valor intermediario em [11, 22, 33, 10, 20, 30] (ruido matematico)

        Alvos:
        - Grupo 1 (terminal 1,4,7): numeros com terminais 1,4,7 + 0 + 10
        - Grupo 2 (terminal 2,5,8): numeros com terminais 2,5,8 + 0 + 20
        """
        triggers = definition.params.get("triggers", [10, 20, 30])
        noise_values = set(definition.params.get("noise_values", [11, 22, 33, 10, 20, 30]))
        include_zero = bool(definition.params.get("include_zero", True))
        include_protection = bool(definition.params.get("include_protection", True))
        max_numbers = max(1, int(definition.max_numbers))

        hist = history[from_index:]
        if len(hist) < 3:
            return {"numbers": [], "explanation": "Historico insuficiente para Black Horse."}

        # Gatilho: numero mais recente deve ser 10, 20 ou 30
        trigger = hist[0]
        if trigger not in triggers:
            return {"numbers": [], "explanation": f"Gatilho {trigger} nao e 10, 20 ou 30."}

        # Numero anterior ao gatilho
        n_prev = hist[1]

        # Cancelamentos imediatos
        if n_prev == 0:
            return {"numbers": [], "explanation": "Numero anterior e 0 - cancelado."}
        if n_prev == trigger:
            return {"numbers": [], "explanation": f"Numero anterior igual ao gatilho ({trigger}) - cancelado."}

        # Loop matematico: subtrai 36 ate encontrar terminal valido
        val = n_prev
        target_group = 0
        math_steps = []
        max_iterations = 10  # Seguranca contra loop infinito

        for _ in range(max_iterations):
            prev_val = val
            val = val - 36
            abs_val = abs(val)
            math_steps.append(f"{prev_val}-36={val}")

            # Ruido matematico - cancela
            if abs_val in noise_values:
                return {
                    "numbers": [],
                    "explanation": f"Ruido matematico: |{val}| = {abs_val} esta em valores de anulacao."
                }

            # Verificar terminal
            term = abs_val % 10
            if term in [1, 4, 7]:
                target_group = 1
                break
            elif term in [2, 5, 8]:
                target_group = 2
                break
            elif term in [3, 6, 9, 0]:
                continue  # Continua o loop
            else:
                return {"numbers": [], "explanation": f"Terminal {term} invalido."}

        if target_group == 0:
            return {"numbers": [], "explanation": "Nenhum grupo alvo encontrado apos loop."}

        # Montar lista de apostas
        scores: Dict[int, float] = defaultdict(float)
        group_name = ""
        protection = 0

        if target_group == 1:
            targets = [1, 4, 7]
            protection = 10
            group_name = "1-4-7"
        else:
            targets = [2, 5, 8]
            protection = 20
            group_name = "2-5-8"

        # Adicionar numeros com terminais do grupo alvo
        for t in targets:
            for n in range(1, 37):
                if n % 10 == t:
                    scores[n] = 10.0

        # Adicionar zero
        if include_zero:
            scores[0] = 10.0

        # Adicionar protecao (10 ou 20)
        if include_protection:
            scores[protection] = 10.0

        sorted_numbers = sorted(scores.keys(), key=lambda n: (-scores[n], n))[:max_numbers]
        final_scores = {n: round(scores[n], 4) for n in sorted_numbers}

        math_str = " | ".join(math_steps)

        return {
            "numbers": sorted_numbers,
            "scores": final_scores,
            "explanation": f"Black Horse: {n_prev} > {trigger} | Decodificacao: {math_str} | Cavalo {group_name} + 0 + Prot({protection})",
        }

    def _eval_puxados_boost(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        """
        Padrao Puxados v3:
        Analisa os numeros que foram "puxados" pelo numero mais recente.
        Usa a logica de build_prediction_from_history simplificada.
        """
        min_history = definition.params.get("min_history", 400)
        window = definition.params.get("window", 3)
        top_window = definition.params.get("top_window", 11)
        top_plus1 = definition.params.get("top_plus1", 3)
        min_indice = definition.params.get("min_indice", 10)
        max_numbers = max(1, int(definition.max_numbers))

        hist = history[from_index:]
        if len(hist) < min_history:
            return {"numbers": [], "explanation": f"Historico insuficiente ({len(hist)}<{min_history})."}

        base = hist[0]

        # Busca primeira ocorrencia de base-1 apos posicao 1
        indice1 = None
        target1 = base - 1 if base > 0 else None
        if target1 is not None:
            for i in range(1, len(hist)):
                if hist[i] == target1:
                    indice1 = i
                    break

        if indice1 is None or indice1 < min_indice:
            return {"numbers": [], "explanation": f"Indice1 nao encontrado ou muito proximo."}

        # Coleta target1 (numeros antes de indice1)
        start1 = max(0, indice1 - 5)
        end1 = indice1 - 1
        target1_nums = hist[start1:end1] if end1 > start1 else []

        # Busca primeira ocorrencia de base+1 apos posicao 1
        indice2 = None
        target2 = base + 1 if base < 36 else None
        if target2 is not None:
            for i in range(1, len(hist)):
                if hist[i] == target2:
                    indice2 = i
                    break

        if indice2 is None or indice2 < min_indice:
            return {"numbers": [], "explanation": f"Indice2 nao encontrado ou muito proximo."}

        start2 = max(0, indice2 - 5)
        end2 = indice2 - 1
        target2_nums = hist[start2:end2] if end2 > start2 else []

        # Analisa puxados do numero base
        pulled_counts: Dict[int, int] = defaultdict(int)
        for i in range(1, min(len(hist), 200)):
            if hist[i] == base and i > 0:
                pulled = hist[i - 1]
                pulled_counts[pulled] += 1

        # Ordena por frequencia e pega os top
        sorted_pulled = sorted(pulled_counts.items(), key=lambda x: (-x[1], x[0]))
        suggestion = [n for n, _ in sorted_pulled[:top_window]]

        # Adiciona 0 no inicio
        if 0 not in suggestion:
            suggestion.insert(0, 0)

        bet_set = set(suggestion)

        # Verifica se houve match com os targets
        if not (set(target1_nums) & bet_set):
            return {"numbers": [], "explanation": f"Sem match com target1."}

        if not (set(target2_nums) & bet_set):
            return {"numbers": [], "explanation": f"Sem match com target2."}

        scores: Dict[int, float] = defaultdict(float)
        for i, n in enumerate(suggestion):
            scores[n] = 10.0 - (i * 0.3)

        sorted_numbers = sorted(scores.keys(), key=lambda n: (-scores[n], n))[:max_numbers]
        final_scores = {n: round(scores[n], 4) for n in sorted_numbers}

        return {
            "numbers": sorted_numbers,
            "scores": final_scores,
            "explanation": f"Puxados: base={base}, {len(suggestion)} numeros sugeridos.",
        }

    def _eval_numeros_puxando_boost(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        """
        Padrao Numeros Puxando:
        Analisa padroes de numeros que puxam outros numeros baseado em frequencia.
        Usa analise de transicoes para encontrar numeros quentes.
        """
        min_history = definition.params.get("min_history", 100)
        analysis_window = definition.params.get("analysis_window", 100)
        max_numbers = max(1, int(definition.max_numbers))
        min_frequency = definition.params.get("min_frequency", 3)
        include_neighbors = bool(definition.params.get("include_neighbors", True))
        neighbor_score_ratio = float(definition.params.get("neighbor_score_ratio", 0.5))

        hist = history[from_index:]
        if len(hist) < min_history:
            return {"numbers": [], "explanation": f"Historico insuficiente ({len(hist)}<{min_history})."}

        # Analisa transicoes: quando A aparece, qual numero vem depois?
        transitions: Dict[int, Dict[int, int]] = defaultdict(lambda: defaultdict(int))
        segment = hist[:analysis_window]

        for i in range(len(segment) - 1):
            curr = segment[i]
            next_num = segment[i + 1]
            transitions[curr][next_num] += 1

        # Para cada numero no historico recente, calcula score baseado em transicoes
        scores: Dict[int, float] = defaultdict(float)

        # Analisa os ultimos 10 numeros como gatilhos potenciais
        for trigger in segment[:10]:
            trans = transitions.get(trigger, {})
            for target, count in trans.items():
                if count >= min_frequency:
                    scores[target] += count * 2.0

        # Adiciona frequencia geral
        freq_counts: Dict[int, int] = defaultdict(int)
        for n in segment:
            freq_counts[n] += 1

        avg_freq = len(segment) / 37
        for n, freq in freq_counts.items():
            if freq > avg_freq * 1.5:
                scores[n] += freq * 0.5

        # Adiciona vizinhos se configurado
        if include_neighbors and scores:
            neighbor_adds: Dict[int, float] = {}
            for n, s in list(scores.items()):
                for nb in self._neighbors(n):
                    if nb not in scores:
                        neighbor_adds[nb] = neighbor_adds.get(nb, 0) + s * neighbor_score_ratio
            scores.update(neighbor_adds)

        # Adiciona 0 se nao estiver
        if 0 not in scores:
            scores[0] = 5.0

        if not scores:
            return {"numbers": [], "explanation": "Nenhum padrao de puxada identificado."}

        sorted_numbers = sorted(scores.keys(), key=lambda n: (-scores[n], n))[:max_numbers]
        final_scores = {n: round(scores[n], 4) for n in sorted_numbers}

        return {
            "numbers": sorted_numbers,
            "scores": final_scores,
            "explanation": f"Numeros Puxando: {len(sorted_numbers)} numeros com padroes de transicao.",
        }

    def _eval_score_boost(
        self,
        history: List[int],
        base_suggestion: List[int],
        from_index: int,
        definition: PatternDefinition,
        focus_number: int | None = None,
    ) -> Dict[str, Any]:
        """
        Padrao Score v5:
        Sistema de scoring avancado baseado em analise completa do historico.
        Combina multiplas metricas: frequencia, vizinhos, espelhos, terminais.
        """
        min_history = definition.params.get("min_history", 200)
        peso_principal = float(definition.params.get("peso_principal", 4.0))
        peso_vizinhos = float(definition.params.get("peso_vizinhos", 2.0))
        peso_vizinhos1 = float(definition.params.get("peso_vizinhos1", 1.2))
        peso_espelho = float(definition.params.get("peso_espelho", 1.5))
        peso_terminal = float(definition.params.get("peso_terminal", 1.0))
        decaimento = float(definition.params.get("decaimento", 0.5))
        max_numbers = max(1, int(definition.max_numbers))

        hist = history[from_index:]
        if len(hist) < min_history:
            return {"numbers": [], "explanation": f"Historico insuficiente ({len(hist)}<{min_history})."}

        base = hist[0]
        scores: Dict[int, float] = defaultdict(float)

        # Score principal: frequencia com decaimento
        for i, n in enumerate(hist[:min_history]):
            decay_factor = decaimento ** (i / 20)
            scores[n] += peso_principal * decay_factor

        # Score de vizinhos na roleta (vizinhos diretos e de segundo nivel)
        for i, n in enumerate(hist[:50]):
            neighbors1 = self._neighbors(n)
            for nb in neighbors1:
                scores[nb] += peso_vizinhos1 * (decaimento ** (i / 10))
                # Vizinhos de segundo nivel
                neighbors2 = self._neighbors(nb)
                for nb2 in neighbors2:
                    if nb2 != n and nb2 not in neighbors1:
                        scores[nb2] += peso_vizinhos * 0.5 * (decaimento ** (i / 10))

        # Score de espelhos
        MIRRORS = {
            1: 10, 10: 1, 2: 20, 20: 2, 3: 30, 30: 3,
            12: 21, 21: 12, 13: 31, 31: 13, 23: 32, 32: 23
        }
        for i, n in enumerate(hist[:30]):
            if n in MIRRORS:
                mirror = MIRRORS[n]
                scores[mirror] += peso_espelho * (decaimento ** (i / 10))

        # Score de terminal
        terminal_base = base % 10
        for n in range(0, 37):
            if n % 10 == terminal_base:
                scores[n] += peso_terminal

        # Adiciona 0 se nao estiver
        if 0 not in scores:
            scores[0] = 5.0

        if not scores:
            return {"numbers": [], "explanation": "Score zerado."}

        sorted_numbers = sorted(scores.keys(), key=lambda n: (-scores[n], n))[:max_numbers]
        final_scores = {n: round(scores[n], 4) for n in sorted_numbers}

        return {
            "numbers": sorted_numbers,
            "scores": final_scores,
            "explanation": f"Score: base={base}, {len(sorted_numbers)} numeros com scoring combinado.",
        }


pattern_engine = PatternEngine()

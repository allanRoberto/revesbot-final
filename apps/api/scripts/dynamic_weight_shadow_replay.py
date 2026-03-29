#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import random
import shutil
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[3]
APPS_ROOT = REPO_ROOT / "apps"
if str(APPS_ROOT) not in sys.path:
    sys.path.insert(0, str(APPS_ROOT))

from api.patterns.engine import PatternEngine
from api.patterns.final_suggestion import (
    build_base_suggestion,
    build_final_suggestion,
    build_focus_context,
    build_runtime_overrides,
    compute_confidence,
    normalize_weights,
)
from api.services.pattern_dynamic_weighting import DynamicWeightConfig, compute_dynamic_weights

ATTEMPTS_SUPPORTED = [1, 2, 3, 4]


@dataclass
class RouletteHistory:
    slug: str
    numbers: List[int]
    numbers_count: int
    order_confirmed: bool
    order_check_source: str
    slug_hash: str
    history_order: str = "most_recent_first"
    order_compare_count: int = 0
    order_values_match: bool = False
    order_single_vs_multi_match: bool = False
    order_inferred_recent_first: bool = False


@dataclass
class ReplayCase:
    slug: str
    history: List[int]
    from_index: int


@dataclass
class ScenarioReplay:
    key: str
    window: Optional[int]
    metrics: Dict[str, Any]
    pattern_metrics: Dict[str, Dict[str, Any]]
    runtime_seconds: float
    weight_summary: Dict[str, Any]


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _safe_div(num: float, den: float) -> float:
    if den <= 0:
        return 0.0
    return num / den


def _sanitize_numbers(raw_values: Any) -> List[int]:
    if not isinstance(raw_values, list):
        return []
    out: List[int] = []
    for value in raw_values:
        try:
            n = int(value)
        except (TypeError, ValueError):
            continue
        if 0 <= n <= 36:
            out.append(n)
    return out


def _http_get_json(url: str, timeout_sec: float) -> Any:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_sec) as response:  # nosec B310
        payload = response.read().decode("utf-8")
    return json.loads(payload)


def _hash_numbers(values: Sequence[int]) -> str:
    joined = ",".join(str(n) for n in values)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _bucket(score: int) -> str:
    score = int(_clamp(float(score), 0.0, 100.0))
    start = (score // 10) * 10
    end = min(100, start + 9)
    return f"{start:02d}-{end:02d}"


def _seed_token(*parts: Any) -> int:
    payload = "|".join(str(p) for p in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def _sample_replay_cases(local_cases: List[ReplayCase], max_cases: int, seed: int, token: str) -> List[ReplayCase]:
    if max_cases <= 0 or len(local_cases) <= max_cases:
        return local_cases
    rng = random.Random(_seed_token(seed, token))
    sample = list(local_cases)
    rng.shuffle(sample)
    sample = sample[:max_cases]
    sample.sort(key=lambda c: c.from_index)
    return sample


def _lookahead_numbers(history: List[int], from_index: int, attempts: int) -> List[int]:
    out: List[int] = []
    for step in range(1, max(1, attempts) + 1):
        idx = from_index - step
        if idx < 0:
            break
        out.append(int(history[idx]))
    return out


def _hit_within(suggestion: Sequence[int], lookahead: Sequence[int], attempts: int) -> bool:
    if not suggestion or not lookahead:
        return False
    target = set(int(n) for n in suggestion)
    return any(int(n) in target for n in list(lookahead)[: max(1, attempts)])


def _resolve_pattern_id(raw_pattern_id: str, known_pattern_ids: Sequence[str]) -> Optional[str]:
    if raw_pattern_id in known_pattern_ids:
        return raw_pattern_id
    for pattern_id in known_pattern_ids:
        if raw_pattern_id.startswith(f"{pattern_id}_"):
            return pattern_id
    return None


def _parse_optimized_ranked_list(number_details: Any, fallback: Sequence[int]) -> List[int]:
    if not isinstance(number_details, list):
        return list(fallback)
    ranked: List[int] = []
    for item in number_details:
        if not isinstance(item, dict):
            continue
        if not bool(item.get("selected", False)):
            continue
        try:
            n = int(item.get("number"))
        except (TypeError, ValueError):
            continue
        if 0 <= n <= 36:
            ranked.append(n)
    if ranked:
        return ranked
    return list(fallback)


def _compute_case_with_engine(
    engine: PatternEngine,
    *,
    history: List[int],
    from_index: int,
    max_numbers: int,
    optimized_max_numbers: int,
) -> Dict[str, Any]:
    normalized_history = [int(n) for n in history if 0 <= int(n) <= 36]
    if len(normalized_history) < 2:
        return {
            "available": False,
            "list": [],
            "confidence_score": 0,
            "contributions": [],
        }

    idx = max(0, min(int(from_index), len(normalized_history) - 1))
    focus_number = int(normalized_history[idx])
    target_size = max(1, min(37, int(max_numbers)))
    optimized_limit = max(1, min(37, int(optimized_max_numbers)))
    final_base_weight, final_optimized_weight = normalize_weights(0.4, 0.6)

    siege_window = 6
    siege_min_occurrences = 3
    siege_min_streak = 2
    siege_veto_relief = 0.4
    inversion_enabled = True
    inversion_context_window = 15
    inversion_penalty_factor = 0.3

    focus_context = build_focus_context(
        history=normalized_history,
        focus_number=focus_number,
        from_index=idx,
    )
    pulled_counts = focus_context["pulled_counts"]
    bucket = focus_context["bucket"]
    pulled_total = len(focus_context["pulled"])

    base_confidence = compute_confidence(bucket, pulled_total)
    base_confidence_score = int(base_confidence.get("score", 0) or 0)

    base_list_ranked = build_base_suggestion(
        bucket=bucket,
        pulled_counts=pulled_counts,
        total_pulled=pulled_total,
        source_arr=normalized_history,
        from_index=idx,
        siege_window=siege_window,
        siege_min_occurrences=siege_min_occurrences,
        siege_min_streak=siege_min_streak,
        siege_veto_relief=siege_veto_relief,
        preserve_ranking=True,
    )
    runtime_overrides = build_runtime_overrides(
        runtime_overrides={},
        siege_window=siege_window,
        siege_min_occurrences=siege_min_occurrences,
        siege_min_streak=siege_min_streak,
    )

    optimized_result = engine.evaluate(
        history=normalized_history,
        base_suggestion=sorted(base_list_ranked),
        focus_number=focus_number,
        from_index=idx,
        max_numbers=optimized_limit,
        runtime_overrides=runtime_overrides,
    )
    opt_list_sorted = _sanitize_numbers(list(optimized_result.get("suggestion", []) or []))
    opt_confidence = int((optimized_result.get("confidence") or {}).get("score", 0) or 0)
    number_details = optimized_result.get("number_details", [])
    opt_list_ranked = _parse_optimized_ranked_list(number_details, opt_list_sorted)

    final_result = build_final_suggestion(
        base_list=base_list_ranked,
        optimized_list=opt_list_ranked,
        optimized_confidence=opt_confidence,
        optimized_confidence_effective=int(
            optimized_result.get("confidence_breakdown", {}).get("calibrated_confidence_v2", 0)
            or opt_confidence
        ),
        number_details=number_details if isinstance(number_details, list) else [],
        base_confidence_score=base_confidence_score,
        max_size=target_size,
        history_arr=normalized_history,
        from_index=idx,
        pulled_counts=pulled_counts,
        base_weight=final_base_weight,
        optimized_weight=final_optimized_weight,
        inversion_enabled=inversion_enabled,
        inversion_context_window=inversion_context_window,
        inversion_penalty_factor=inversion_penalty_factor,
    )

    suggestion = _sanitize_numbers(final_result.get("list", []) if isinstance(final_result, dict) else [])
    available = bool(final_result.get("available", False)) and bool(suggestion)
    confidence = int((final_result.get("confidence") or {}).get("score", 0) or 0)
    contributions = optimized_result.get("contributions", [])
    if not isinstance(contributions, list):
        contributions = []

    return {
        "available": available,
        "list": suggestion,
        "confidence_score": confidence,
        "contributions": contributions,
    }


def _load_definition_metadata(definitions_dir: Path) -> Dict[str, Dict[str, Any]]:
    metadata: Dict[str, Dict[str, Any]] = {}
    for path in sorted(definitions_dir.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        pattern_id = str(raw.get("id", "")).strip()
        if not pattern_id:
            continue
        metadata[pattern_id] = {
            "pattern_id": pattern_id,
            "base_weight": float(raw.get("weight", 1.0)),
            "kind": str(raw.get("kind", "positive")).lower().strip(),
            "active": bool(raw.get("active", True)),
            "filename": path.name,
        }
    return metadata


@contextlib.contextmanager
def _shadow_engine_context(
    *,
    definitions_dir: Path,
    dynamic_weights: Mapping[str, float],
    disabled_patterns: Sequence[str] | None = None,
) -> Tuple[PatternEngine, Dict[str, Any]]:
    disabled = set(str(pid) for pid in (disabled_patterns or []))
    tmp_dir = Path(tempfile.mkdtemp(prefix="dynamic-weight-shadow-"))
    applied_dynamic: Dict[str, Dict[str, Any]] = {}

    try:
        for source_path in sorted(definitions_dir.glob("*.json")):
            target_path = tmp_dir / source_path.name
            try:
                raw = json.loads(source_path.read_text(encoding="utf-8"))
            except Exception:
                continue

            pattern_id = str(raw.get("id", "")).strip()
            kind = str(raw.get("kind", "positive")).lower().strip()
            base_weight = float(raw.get("weight", 1.0))
            dynamic_weight = float(dynamic_weights.get(pattern_id, 1.0))
            effective_weight = base_weight

            if pattern_id in disabled:
                raw["active"] = False
            elif kind == "positive" and pattern_id != "legacy_base_suggestion":
                effective_weight = base_weight * dynamic_weight
                raw["weight"] = round(effective_weight, 6)

            if kind == "positive":
                applied_dynamic[pattern_id] = {
                    "base_weight": round(base_weight, 6),
                    "dynamic_weight": round(dynamic_weight, 6),
                    "effective_weight": round(effective_weight, 6),
                    "disabled": pattern_id in disabled,
                }

            target_path.write_text(json.dumps(raw, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

        yield PatternEngine(patterns_dir=tmp_dir), {"applied_dynamic": applied_dynamic}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _run_replay(
    *,
    engine: PatternEngine,
    cases: Sequence[ReplayCase],
    known_pattern_ids: Sequence[str],
    attempts: int,
    max_numbers: int,
    optimized_max_numbers: int,
) -> Dict[str, Any]:
    ordered_cases = sorted(cases, key=lambda c: (c.slug, c.from_index))
    total_cases = len(ordered_cases)
    available_cases = 0
    hits_abs = {k: 0 for k in ATTEMPTS_SUPPORTED}
    list_sizes: List[int] = []
    confidence_dist: Dict[str, int] = {}
    pattern_stats: Dict[str, Dict[str, Any]] = {}

    known_ids = sorted(set(known_pattern_ids), key=len, reverse=True)

    for case in ordered_cases:
        result = _compute_case_with_engine(
            engine,
            history=case.history,
            from_index=case.from_index,
            max_numbers=max_numbers,
            optimized_max_numbers=optimized_max_numbers,
        )
        suggestion = list(result.get("list", []))
        available = bool(result.get("available", False)) and bool(suggestion)
        lookahead = _lookahead_numbers(case.history, case.from_index, attempts)

        if available:
            available_cases += 1
            list_sizes.append(len(suggestion))
            conf_score = int(result.get("confidence_score", 0) or 0)
            conf_key = _bucket(conf_score)
            confidence_dist[conf_key] = confidence_dist.get(conf_key, 0) + 1
            for k in ATTEMPTS_SUPPORTED:
                if _hit_within(suggestion, lookahead, k):
                    hits_abs[k] += 1

        contributions = result.get("contributions", [])
        if not isinstance(contributions, list):
            contributions = []
        for item in contributions:
            if not isinstance(item, dict):
                continue
            raw_pattern_id = str(item.get("pattern_id", "")).strip()
            resolved_pattern_id = _resolve_pattern_id(raw_pattern_id, known_ids)
            if not resolved_pattern_id:
                continue
            numbers = _sanitize_numbers(item.get("numbers", []))
            if not numbers:
                continue

            row = pattern_stats.setdefault(
                resolved_pattern_id,
                {
                    "sample_size": 0,
                    "hits_at_1": 0,
                    "hits_at_2": 0,
                    "hits_at_3": 0,
                    "hits_at_4": 0,
                    "recent_outcomes": [],
                },
            )
            row["sample_size"] += 1
            hit1 = _hit_within(numbers, lookahead, 1)
            hit2 = _hit_within(numbers, lookahead, 2)
            hit3 = _hit_within(numbers, lookahead, 3)
            hit4 = _hit_within(numbers, lookahead, min(4, attempts))
            row["hits_at_1"] += int(hit1)
            row["hits_at_2"] += int(hit2)
            row["hits_at_3"] += int(hit3)
            row["hits_at_4"] += int(hit4)
            row["recent_outcomes"].append(bool(hit4))

    effective_hits = {f"hit@{k}": round(_safe_div(hits_abs[k], total_cases), 6) for k in ATTEMPTS_SUPPORTED}
    conditional_hits = {
        f"hit@{k}": round(_safe_div(hits_abs[k], available_cases), 6) for k in ATTEMPTS_SUPPORTED
    }

    for pattern_id, row in pattern_stats.items():
        sample = max(1, int(row["sample_size"]))
        row["coverage"] = round(_safe_div(row["sample_size"], total_cases), 6)
        row["hit_rate"] = round(_safe_div(row["hits_at_4"], sample), 6)
        row["hit@1"] = round(_safe_div(row["hits_at_1"], sample), 6)
        row["hit@2"] = round(_safe_div(row["hits_at_2"], sample), 6)
        row["hit@3"] = round(_safe_div(row["hits_at_3"], sample), 6)
        row["hit@4"] = round(_safe_div(row["hits_at_4"], sample), 6)

    return {
        "metrics": {
            "eligible_cases": total_cases,
            "available_cases": available_cases,
            "coverage": round(_safe_div(available_cases, total_cases), 6),
            "effective_hits": effective_hits,
            "conditional_hits": conditional_hits,
            "avg_list_size": round(mean(list_sizes), 6) if list_sizes else 0.0,
            "avg_list_size_all_cases": round(_safe_div(sum(list_sizes), total_cases), 6),
            "confidence_distribution": dict(sorted(confidence_dist.items(), key=lambda kv: kv[0])),
        },
        "pattern_metrics": pattern_stats,
    }


def _aggregate_baseline_pattern_hit_rate(pattern_metrics: Mapping[str, Mapping[str, Any]]) -> float:
    hits = 0
    samples = 0
    for row in pattern_metrics.values():
        hits += int(row.get("hits_at_4", 0) or 0)
        samples += int(row.get("sample_size", 0) or 0)
    if samples <= 0:
        return 0.5
    return _clamp(hits / samples, 1e-4, 1.0)


def _build_training_cases(
    histories: Mapping[str, RouletteHistory],
    *,
    window: int,
    attempts: int,
    max_cases_per_roulette: int,
    seed: int,
) -> List[ReplayCase]:
    cases: List[ReplayCase] = []
    max_idx = max(0, window - 1)
    for slug, item in sorted(histories.items(), key=lambda kv: kv[0]):
        history = item.numbers
        if len(history) <= attempts:
            continue
        local: List[ReplayCase] = []
        upper = min(len(history) - 1, max_idx)
        for idx in range(attempts, upper + 1):
            local.append(ReplayCase(slug=slug, history=history, from_index=idx))
        local = _sample_replay_cases(
            local,
            max_cases=max_cases_per_roulette,
            seed=seed,
            token=f"train:{slug}:w{window}",
        )
        cases.extend(local)
    return cases


def _build_eval_cases(
    histories: Mapping[str, RouletteHistory],
    *,
    holdout_start: int,
    attempts: int,
    max_cases_per_roulette: int,
    seed: int,
) -> List[ReplayCase]:
    cases: List[ReplayCase] = []
    for slug, item in sorted(histories.items(), key=lambda kv: kv[0]):
        history = item.numbers
        if len(history) <= attempts:
            continue
        local: List[ReplayCase] = []
        start = max(attempts, holdout_start)
        for idx in range(start, len(history)):
            local.append(ReplayCase(slug=slug, history=history, from_index=idx))
        local = _sample_replay_cases(
            local,
            max_cases=max_cases_per_roulette,
            seed=seed,
            token=f"eval:{slug}:h{holdout_start}",
        )
        cases.extend(local)
    return cases


def _build_all_cases(
    histories: Mapping[str, RouletteHistory],
    *,
    attempts: int,
    max_cases_per_roulette: int,
    seed: int,
) -> List[ReplayCase]:
    return _build_eval_cases(
        histories,
        holdout_start=attempts,
        attempts=attempts,
        max_cases_per_roulette=max_cases_per_roulette,
        seed=seed,
    )


def _fetch_history_for_slug(base_url: str, slug: str, limit: int, timeout_sec: float) -> RouletteHistory:
    encoded_slug = urllib.parse.quote(slug, safe="")
    history_url = f"{base_url.rstrip('/')}/history/{encoded_slug}?limit={max(1, int(limit))}"
    payload = _http_get_json(history_url, timeout_sec=timeout_sec)
    if isinstance(payload, dict):
        numbers = _sanitize_numbers(payload.get("results", []))
    else:
        numbers = _sanitize_numbers(payload)

    order_confirmed = False
    order_check_source = "history-single-vs-multi"
    order_compare_count = 0
    order_values_match = False
    order_single_vs_multi_match = False
    order_inferred_recent_first = False

    # Primary validation without relying on history-detailed:
    # Compare /history?limit=1 against /history?limit=20 to infer orientation.
    # If the newest item is first, the single-item query should match the first
    # positions of the multi query (allowing tiny offset for live updates).
    try:
        multi_url = f"{base_url.rstrip('/')}/history/{encoded_slug}?limit=20"
        single_url = f"{base_url.rstrip('/')}/history/{encoded_slug}?limit=1"
        multi_payload = _http_get_json(multi_url, timeout_sec=timeout_sec)
        single_payload = _http_get_json(single_url, timeout_sec=timeout_sec)
        multi = _sanitize_numbers(multi_payload.get("results", []) if isinstance(multi_payload, dict) else multi_payload)
        single = _sanitize_numbers(
            single_payload.get("results", []) if isinstance(single_payload, dict) else single_payload
        )

        if multi and single:
            one = int(single[0])
            head_positions = multi[:3]
            tail_positions = multi[-3:]
            order_single_vs_multi_match = one in multi
            order_inferred_recent_first = one in head_positions and one not in tail_positions
            # In live stream, newest may shift one or two places between calls.
            if one in head_positions:
                order_values_match = True
                order_compare_count = 1
                order_confirmed = True
            else:
                order_values_match = False
                order_compare_count = 1
                order_confirmed = False
        else:
            order_confirmed = False
    except Exception:
        order_confirmed = False
        order_check_source = "history-contract-only-failed"

    return RouletteHistory(
        slug=slug,
        numbers=numbers,
        numbers_count=len(numbers),
        order_confirmed=bool(order_confirmed),
        order_check_source=order_check_source,
        slug_hash=_hash_numbers(numbers),
        order_compare_count=int(order_compare_count),
        order_values_match=bool(order_values_match),
        order_single_vs_multi_match=bool(order_single_vs_multi_match),
        order_inferred_recent_first=bool(order_inferred_recent_first),
    )


def _fetch_slugs(base_url: str, provided_slugs: Sequence[str], max_roulettes: int, timeout_sec: float) -> List[str]:
    if provided_slugs:
        clean = [slug.strip() for slug in provided_slugs if slug and slug.strip()]
        return sorted(set(clean))

    url = f"{base_url.rstrip('/')}/api/roulettes-list"
    payload = _http_get_json(url, timeout_sec=timeout_sec)
    if not isinstance(payload, list):
        return []
    out: List[str] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("id", "")).strip()
        if not slug:
            continue
        out.append(slug)
    if max_roulettes > 0:
        out = out[:max_roulettes]
    return sorted(set(out))


def _build_global_input_hash(histories: Mapping[str, RouletteHistory]) -> str:
    canonical = {
        slug: {
            "numbers": item.numbers,
            "slug_hash": item.slug_hash,
            "order_confirmed": item.order_confirmed,
        }
        for slug, item in sorted(histories.items(), key=lambda kv: kv[0])
    }
    payload = json.dumps(canonical, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _write_snapshot(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _format_metrics_row(label: str, metrics: Dict[str, Any]) -> str:
    effective = metrics.get("effective_hits", {})
    return (
        f"| {label} | {metrics.get('coverage', 0.0):.4f} | "
        f"{effective.get('hit@1', 0.0):.4f} | {effective.get('hit@2', 0.0):.4f} | "
        f"{effective.get('hit@3', 0.0):.4f} | {effective.get('hit@4', 0.0):.4f} | "
        f"{metrics.get('avg_list_size', 0.0):.3f} |"
    )


def _write_markdown_report(path: Path, payload: Dict[str, Any]) -> None:
    scenarios = payload.get("scenarios", {})
    baseline = scenarios.get("baseline", {}).get("metrics", {})
    candidate_rows = []
    for key, row in sorted(scenarios.items(), key=lambda kv: kv[0]):
        if key == "baseline":
            continue
        candidate_rows.append((key, row.get("metrics", {})))

    ablation = payload.get("ablation", {}).get("rows", [])
    ablation_sorted = sorted(
        [r for r in ablation if isinstance(r, dict)],
        key=lambda r: float(r.get("delta_effective_hit@4_remove_pattern", 0.0)),
        reverse=True,
    )

    top_positive = ablation_sorted[:10]
    top_negative = list(reversed(ablation_sorted[-10:])) if len(ablation_sorted) > 10 else []
    used_count = int(payload.get("input", {}).get("used_roulettes_count", 0) or 0)
    discarded_count = int(payload.get("input", {}).get("discarded_roulettes_count", 0) or 0)
    eval_cases = int(payload.get("input", {}).get("eval_cases", 0) or 0)

    candidate_hit4: Dict[str, float] = {}
    for key, row in scenarios.items():
        if not str(key).startswith("candidate_w"):
            continue
        metrics = row.get("metrics", {}) if isinstance(row, dict) else {}
        candidate_hit4[str(key)] = float((metrics.get("effective_hits") or {}).get("hit@4", 0.0))
    sorted_candidates = sorted(candidate_hit4.items(), key=lambda kv: kv[1], reverse=True)
    best_candidate = sorted_candidates[0][0] if sorted_candidates else "n/a"
    second_best_val = sorted_candidates[1][1] if len(sorted_candidates) > 1 else sorted_candidates[0][1] if sorted_candidates else 0.0
    best_candidate_val = sorted_candidates[0][1] if sorted_candidates else 0.0
    best_gap = best_candidate_val - second_best_val

    if eval_cases >= 1000 and used_count >= 5:
        sufficiency = "sinal estatístico inicial moderado (rodada intermediária robusta)"
    elif eval_cases >= 500 and used_count >= 4:
        sufficiency = "sinal estatístico inicial, ainda com cautela"
    else:
        sufficiency = "massa ainda limitada para conclusão estatística"

    aggregators = [r for r in ablation_sorted if float(r.get("delta_effective_hit@4_remove_pattern", 0.0)) > 0.002]
    harmful = [r for r in ablation_sorted if float(r.get("delta_effective_hit@4_remove_pattern", 0.0)) < -0.002]
    neutral = [
        r
        for r in ablation_sorted
        if abs(float(r.get("delta_effective_hit@4_remove_pattern", 0.0))) <= 0.001
    ]

    roulette_lines_used = []
    for row in payload.get("input", {}).get("used_roulettes", []):
        roulette_lines_used.append(
            "- "
            f"{row.get('slug')}: count={row.get('numbers_count')}, "
            f"order={row.get('history_order')}, "
            f"order_confirmed={row.get('order_confirmed')}, "
            f"check_source={row.get('order_check_source')}, "
            f"hash={row.get('slug_hash')}"
        )

    roulette_lines_discarded = []
    for row in payload.get("input", {}).get("discarded_roulettes", []):
        roulette_lines_discarded.append(
            "- "
            f"{row.get('slug')}: reason={row.get('reason')}, "
            f"details={row.get('details', {})}"
        )

    md_lines = [
        "# Dynamic Weighting Shadow Replay Report",
        "",
        f"Generated at: {payload.get('generated_at')}",
        f"Mode: {'SMOKE/PREVIEW' if payload.get('smoke_mode') else 'FULL'}",
        f"Stage: {'intermediate' if not payload.get('smoke_mode') else 'smoke-preview'}",
        "",
        "## Scope",
        "- Shadow only: no production runtime changes.",
        "- Data source: `/history/{slug}`.",
        "",
        "## Input Summary",
        f"- Base URL: `{payload.get('input', {}).get('base_url')}`",
        f"- Seed: `{payload.get('input', {}).get('seed')}`",
        f"- Global input hash: `{payload.get('input', {}).get('global_input_hash')}`",
        f"- Holdout leakage fallback: `{payload.get('input', {}).get('holdout_leakage_fallback')}`",
        f"- Total de casos avaliados: `{payload.get('input', {}).get('eval_cases')}`",
        f"- Windows: `{payload.get('config', {}).get('windows')}`",
        f"- Roulettes usadas: `{used_count}`",
        f"- Roulettes descartadas: `{discarded_count}`",
        "",
        "### Roulettes usadas",
        *roulette_lines_used,
        "",
        "### Roulettes descartadas",
        *(roulette_lines_discarded if roulette_lines_discarded else ["- nenhuma"]),
        "",
        "## Scenario Comparison",
        "| Scenario | coverage | e_hit@1 | e_hit@2 | e_hit@3 | e_hit@4 | avg_list_size |",
        "|---|---:|---:|---:|---:|---:|---:|",
        _format_metrics_row("baseline", baseline),
    ]
    for key, metrics in candidate_rows:
        md_lines.append(_format_metrics_row(key, metrics))

    md_lines.extend(
        [
            "",
            "## Intermediate Assessment",
            f"- Total de casos avaliados: `{eval_cases}`",
            f"- Melhor janela/candidate até agora: `{best_candidate}` (effective_hit@4={best_candidate_val:.6f})",
            f"- Diferença para 2o colocado: `{best_gap:.6f}`",
            f"- candidate_w200: `{candidate_hit4.get('candidate_w200', 0.0):.6f}`",
            f"- Suficiência de sinal nesta rodada: **{sufficiency}**",
            f"- Padrões aparentemente agregadores (ablação): `{len(aggregators)}`",
            f"- Padrões aparentemente neutros (ablação): `{len(neutral)}`",
            f"- Padrões aparentemente prejudiciais (ablação): `{len(harmful)}`",
            "",
            "## Ablation (selected scenario)",
            f"- Scenario: `{payload.get('ablation', {}).get('scenario')}`",
            f"- Patterns analyzed: `{payload.get('ablation', {}).get('patterns_analyzed')}`",
            "",
            "### Top Positive Delta (remove pattern hurts)",
            "| pattern_id | sample_size | delta_coverage | delta_effective_hit@4_remove_pattern |",
            "|---|---:|---:|---:|",
        ]
    )
    for row in top_positive:
        md_lines.append(
            "| "
            f"{row.get('pattern_id')} | {row.get('sample_size', 0)} | "
            f"{row.get('delta_coverage', 0.0):.6f} | "
            f"{row.get('delta_effective_hit@4_remove_pattern', 0.0):.6f} |"
        )

    if top_negative:
        md_lines.extend(
            [
                "",
                "### Top Negative Delta (remove pattern improves)",
                "| pattern_id | sample_size | delta_coverage | delta_effective_hit@4_remove_pattern |",
                "|---|---:|---:|---:|",
            ]
        )
        for row in top_negative:
            md_lines.append(
                "| "
                f"{row.get('pattern_id')} | {row.get('sample_size', 0)} | "
                f"{row.get('delta_coverage', 0.0):.6f} | "
                f"{row.get('delta_effective_hit@4_remove_pattern', 0.0):.6f} |"
            )

    md_lines.extend(
        [
            "",
            "## Notes",
            "- This report is generated from API history and is reproducible via input hash + config.",
            "- Promotion to production remains manual after objective validation criteria.",
            "",
        ]
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(md_lines), encoding="utf-8")


def _parse_windows(raw: str) -> List[int]:
    out: List[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            n = int(part)
        except ValueError:
            continue
        if n > 0:
            out.append(n)
    if not out:
        out = [100, 200, 500]
    return sorted(set(out))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dynamic pattern weighting shadow replay (API /history source).")
    parser.add_argument("--base-url", default=os.getenv("BASE_URL_API", "http://localhost:8000"))
    parser.add_argument("--slugs", default="", help="Comma separated roulette slugs. Empty => /api/roulettes-list.")
    parser.add_argument("--max-roulettes", type=int, default=2)
    parser.add_argument("--history-limit", type=int, default=220)
    parser.add_argument("--windows", default="100,200,500")
    parser.add_argument("--attempts", type=int, default=4)
    parser.add_argument("--max-numbers", type=int, default=12)
    parser.add_argument("--optimized-max-numbers", type=int, default=37)
    parser.add_argument("--max-cases-per-roulette", type=int, default=90)
    parser.add_argument("--min-total-cases", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20260310)
    parser.add_argument("--timeout-sec", type=float, default=15.0)
    parser.add_argument("--smoke", action="store_true", default=False)
    parser.add_argument("--ablation-scenario", default="auto")
    parser.add_argument("--ablation-close-threshold", type=float, default=0.002)
    parser.add_argument("--ablation-max-patterns", type=int, default=0, help="0 = todos os padrões.")
    parser.add_argument("--snapshot-dir", type=Path, default=REPO_ROOT / "apps" / "api" / "data" / "dynamic_weight_snapshots")
    parser.add_argument("--report-dir", type=Path, default=REPO_ROOT / "docs")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    started_at = time.perf_counter()

    windows = _parse_windows(str(args.windows))
    attempts = max(1, min(4, int(args.attempts)))
    seed = int(args.seed)
    slugs_arg = [part.strip() for part in str(args.slugs).split(",") if part.strip()]
    base_url = str(args.base_url).rstrip("/")
    max_cases = max(0, int(args.max_cases_per_roulette))
    min_total_cases = max(1, int(args.min_total_cases))
    max_roulettes = max(1, int(args.max_roulettes))
    history_limit = max(20, int(args.history_limit))
    timeout_sec = max(2.0, float(args.timeout_sec))

    if args.smoke:
        max_roulettes = min(max_roulettes, 3)
        history_limit = min(history_limit, 220)
        max_cases = min(max_cases, 90)
        if int(args.ablation_max_patterns) <= 0:
            args.ablation_max_patterns = 12

    slugs = _fetch_slugs(base_url, slugs_arg, max_roulettes=max_roulettes, timeout_sec=timeout_sec)
    if not slugs:
        raise RuntimeError("Nenhuma roleta encontrada para replay via /history/{slug}.")

    holdout_start = max(windows)
    histories: Dict[str, RouletteHistory] = {}
    discarded_roulettes: List[Dict[str, Any]] = []
    for slug in slugs:
        try:
            row = _fetch_history_for_slug(base_url, slug, limit=history_limit, timeout_sec=timeout_sec)
        except Exception as exc:
            discarded_roulettes.append(
                {"slug": slug, "reason": "fetch_failed", "details": {"error": str(exc)}}
            )
            continue

        min_numbers_required = holdout_start + attempts + 2
        if row.numbers_count < min_numbers_required:
            discarded_roulettes.append(
                {
                    "slug": slug,
                    "reason": "insufficient_history",
                    "details": {"numbers_count": row.numbers_count, "min_required": min_numbers_required},
                }
            )
            continue
        if not row.order_confirmed:
            discarded_roulettes.append(
                {
                    "slug": slug,
                    "reason": "order_validation_failed",
                    "details": {
                        "order_check_source": row.order_check_source,
                        "order_values_match": row.order_values_match,
                        "order_single_vs_multi_match": row.order_single_vs_multi_match,
                        "order_inferred_recent_first": row.order_inferred_recent_first,
                    },
                }
            )
            continue
        histories[slug] = row

    if not histories:
        raise RuntimeError("Nenhuma roleta passou na validação de ordem + histórico mínimo.")

    definitions_dir = REPO_ROOT / "apps" / "api" / "patterns" / "definitions"
    definition_meta = _load_definition_metadata(definitions_dir)
    known_positive_patterns = sorted(
        [
            pid
            for pid, meta in definition_meta.items()
            if bool(meta.get("active", False)) and str(meta.get("kind", "")) == "positive"
        ]
    )

    eval_cases = _build_eval_cases(
        histories,
        holdout_start=holdout_start,
        attempts=attempts,
        max_cases_per_roulette=max_cases,
        seed=seed,
    )
    holdout_leakage_fallback = False
    if not eval_cases:
        holdout_leakage_fallback = True
        eval_cases = _build_all_cases(histories, attempts=attempts, max_cases_per_roulette=max_cases, seed=seed)

    if not eval_cases:
        raise RuntimeError("Sem casos elegíveis para avaliação.")
    if len(eval_cases) < min_total_cases:
        raise RuntimeError(
            f"Massa insuficiente de casos ({len(eval_cases)} < {min_total_cases}) após descartar roletas inválidas."
        )

    scenarios: Dict[str, ScenarioReplay] = {}
    window_training_summaries: Dict[str, Any] = {}

    with _shadow_engine_context(definitions_dir=definitions_dir, dynamic_weights={}) as (baseline_engine, baseline_meta):
        t0 = time.perf_counter()
        baseline_eval = _run_replay(
            engine=baseline_engine,
            cases=eval_cases,
            known_pattern_ids=known_positive_patterns,
            attempts=attempts,
            max_numbers=args.max_numbers,
            optimized_max_numbers=args.optimized_max_numbers,
        )
        baseline_runtime = time.perf_counter() - t0
        scenarios["baseline"] = ScenarioReplay(
            key="baseline",
            window=None,
            metrics=baseline_eval["metrics"],
            pattern_metrics=baseline_eval["pattern_metrics"],
            runtime_seconds=baseline_runtime,
            weight_summary=baseline_meta["applied_dynamic"],
        )

        for window in windows:
            train_cases = _build_training_cases(
                histories,
                window=window,
                attempts=attempts,
                max_cases_per_roulette=max_cases,
                seed=seed,
            )
            if not train_cases:
                window_training_summaries[str(window)] = {
                    "window": window,
                    "training_cases": 0,
                    "dynamic_weights": {},
                    "details": {},
                }
                continue

            train_result = _run_replay(
                engine=baseline_engine,
                cases=train_cases,
                known_pattern_ids=known_positive_patterns,
                attempts=attempts,
                max_numbers=args.max_numbers,
                optimized_max_numbers=args.optimized_max_numbers,
            )
            train_pattern_metrics = train_result["pattern_metrics"]
            baseline_pattern_rate = _aggregate_baseline_pattern_hit_rate(train_pattern_metrics)

            config = DynamicWeightConfig()
            dynamic_result = compute_dynamic_weights(
                train_pattern_metrics,
                baseline_hit_rate=baseline_pattern_rate,
                previous_weights=None,
                config=config,
            )
            dynamic_weights = dynamic_result["weights"]
            window_training_summaries[str(window)] = {
                "window": window,
                "training_cases": len(train_cases),
                "baseline_pattern_hit_rate": round(baseline_pattern_rate, 6),
                "dynamic_weights": dynamic_weights,
                "details": dynamic_result["details"],
                "config": dynamic_result["config"],
            }

            scenario_key = f"candidate_w{window}"
            with _shadow_engine_context(
                definitions_dir=definitions_dir,
                dynamic_weights=dynamic_weights,
            ) as (candidate_engine, candidate_meta):
                t1 = time.perf_counter()
                candidate_eval = _run_replay(
                    engine=candidate_engine,
                    cases=eval_cases,
                    known_pattern_ids=known_positive_patterns,
                    attempts=attempts,
                    max_numbers=args.max_numbers,
                    optimized_max_numbers=args.optimized_max_numbers,
                )
                candidate_runtime = time.perf_counter() - t1
                scenarios[scenario_key] = ScenarioReplay(
                    key=scenario_key,
                    window=window,
                    metrics=candidate_eval["metrics"],
                    pattern_metrics=candidate_eval["pattern_metrics"],
                    runtime_seconds=candidate_runtime,
                    weight_summary=candidate_meta["applied_dynamic"],
                )

    requested_ablation_scenario = str(args.ablation_scenario).strip()
    if requested_ablation_scenario.lower() == "auto":
        candidate_keys = [k for k in scenarios.keys() if k.startswith("candidate_w")]
        if candidate_keys:
            scored = sorted(
                candidate_keys,
                key=lambda key: float((scenarios[key].metrics.get("effective_hits") or {}).get("hit@4", 0.0)),
                reverse=True,
            )
            best_key = scored[0]
            best_val = float((scenarios[best_key].metrics.get("effective_hits") or {}).get("hit@4", 0.0))
            close_threshold = max(0.0, float(args.ablation_close_threshold))
            close_keys = [
                key
                for key in scored
                if abs(float((scenarios[key].metrics.get("effective_hits") or {}).get("hit@4", 0.0)) - best_val)
                <= close_threshold
            ]
            if len(close_keys) > 1 and "candidate_w200" in close_keys:
                requested_ablation_scenario = "candidate_w200"
            else:
                requested_ablation_scenario = best_key
        else:
            requested_ablation_scenario = "baseline"
    elif requested_ablation_scenario not in scenarios:
        preferred = "candidate_w200"
        if preferred in scenarios:
            requested_ablation_scenario = preferred
        else:
            candidate_keys = [k for k in scenarios.keys() if k != "baseline"]
            requested_ablation_scenario = candidate_keys[0] if candidate_keys else "baseline"

    ablation_rows: List[Dict[str, Any]] = []
    ablation_scenario = scenarios[requested_ablation_scenario]
    ablation_weights = {
        pid: row.get("dynamic_weight", 1.0)
        for pid, row in window_training_summaries.get(str(ablation_scenario.window), {}).get("details", {}).items()
    }
    baseline_metrics = ablation_scenario.metrics
    baseline_pattern_metrics = ablation_scenario.pattern_metrics
    patterns_for_ablation = [
        pid
        for pid, row in baseline_pattern_metrics.items()
        if int(row.get("sample_size", 0) or 0) > 0
    ]
    patterns_for_ablation.sort(
        key=lambda pid: int(baseline_pattern_metrics.get(pid, {}).get("sample_size", 0) or 0),
        reverse=True,
    )
    max_ablation_patterns = max(0, int(args.ablation_max_patterns))
    if max_ablation_patterns > 0:
        patterns_for_ablation = patterns_for_ablation[:max_ablation_patterns]
    patterns_for_ablation = sorted(patterns_for_ablation)

    for idx, pattern_id in enumerate(patterns_for_ablation, start=1):
        if idx == 1 or idx % 5 == 0:
            print(
                f"[ablation] {idx}/{len(patterns_for_ablation)} pattern={pattern_id}",
                file=sys.stderr,
                flush=True,
            )
        with _shadow_engine_context(
            definitions_dir=definitions_dir,
            dynamic_weights=ablation_weights,
            disabled_patterns=[pattern_id],
        ) as (ablated_engine, _meta):
            replay = _run_replay(
                engine=ablated_engine,
                cases=eval_cases,
                known_pattern_ids=known_positive_patterns,
                attempts=attempts,
                max_numbers=args.max_numbers,
                optimized_max_numbers=args.optimized_max_numbers,
            )
            ablated_metrics = replay["metrics"]
            delta_cov = float(baseline_metrics.get("coverage", 0.0)) - float(ablated_metrics.get("coverage", 0.0))
            baseline_hit4 = float((baseline_metrics.get("effective_hits") or {}).get("hit@4", 0.0))
            ablated_hit4 = float((ablated_metrics.get("effective_hits") or {}).get("hit@4", 0.0))
            ablation_rows.append(
                {
                    "pattern_id": pattern_id,
                    "sample_size": int(baseline_pattern_metrics.get(pattern_id, {}).get("sample_size", 0) or 0),
                    "delta_coverage": round(delta_cov, 6),
                    "delta_effective_hit@4_remove_pattern": round(baseline_hit4 - ablated_hit4, 6),
                }
            )

    generated_at = datetime.now(timezone.utc).isoformat()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot_path = args.snapshot_dir / f"{timestamp}.json"
    report_path = args.report_dir / f"dynamic-weighting-shadow-report-{timestamp}.md"

    roulette_payload_used = [
        {
            "slug": row.slug,
            "numbers_count": row.numbers_count,
            "history_order": row.history_order,
            "order_confirmed": row.order_confirmed,
            "order_check_source": row.order_check_source,
            "order_compare_count": row.order_compare_count,
            "order_values_match": row.order_values_match,
            "order_single_vs_multi_match": row.order_single_vs_multi_match,
            "order_inferred_recent_first": row.order_inferred_recent_first,
            "slug_hash": row.slug_hash,
        }
        for _, row in sorted(histories.items(), key=lambda kv: kv[0])
    ]

    scenarios_payload = {
        key: {
            "window": scenario.window,
            "runtime_seconds": round(scenario.runtime_seconds, 3),
            "metrics": scenario.metrics,
            "pattern_metrics_sampled": {
                pid: {
                    "sample_size": int(row.get("sample_size", 0) or 0),
                    "coverage": float(row.get("coverage", 0.0) or 0.0),
                    "hit_rate": float(row.get("hit_rate", 0.0) or 0.0),
                    "hit@1": float(row.get("hit@1", 0.0) or 0.0),
                    "hit@2": float(row.get("hit@2", 0.0) or 0.0),
                    "hit@3": float(row.get("hit@3", 0.0) or 0.0),
                    "hit@4": float(row.get("hit@4", 0.0) or 0.0),
                }
                for pid, row in sorted(scenario.pattern_metrics.items(), key=lambda kv: kv[0])
            },
            "effective_weights": scenario.weight_summary,
        }
        for key, scenario in sorted(scenarios.items(), key=lambda kv: kv[0])
    }

    snapshot_payload = {
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "smoke_mode": bool(args.smoke),
        "input": {
            "base_url": base_url,
            "source_endpoint": "/history/{slug}",
            "seed": seed,
            "global_input_hash": _build_global_input_hash(histories),
            "used_roulettes": roulette_payload_used,
            "discarded_roulettes": discarded_roulettes,
            "used_roulettes_count": len(roulette_payload_used),
            "discarded_roulettes_count": len(discarded_roulettes),
            "history_limit": history_limit,
            "eval_cases": len(eval_cases),
            "holdout_start": holdout_start,
            "holdout_leakage_fallback": holdout_leakage_fallback,
        },
        "config": {
            "windows": windows,
            "attempts": attempts,
            "seed": seed,
            "max_numbers": int(args.max_numbers),
            "optimized_max_numbers": int(args.optimized_max_numbers),
            "max_cases_per_roulette": max_cases,
            "min_total_cases": min_total_cases,
            "ablation_close_threshold": float(args.ablation_close_threshold),
        },
        "training": window_training_summaries,
        "scenarios": scenarios_payload,
        "ablation": {
            "scenario": requested_ablation_scenario,
            "patterns_analyzed": len(ablation_rows),
            "rows": sorted(ablation_rows, key=lambda r: r["pattern_id"]),
        },
        "runtime_seconds_total": round(time.perf_counter() - started_at, 3),
    }

    _write_snapshot(snapshot_path, snapshot_payload)
    _write_markdown_report(report_path, snapshot_payload)

    print(
        json.dumps(
            {
                "snapshot": str(snapshot_path),
                "report": str(report_path),
                "smoke_mode": bool(args.smoke),
                "scenarios": sorted(scenarios.keys()),
                "ablation_scenario": requested_ablation_scenario,
                "ablation_patterns": len(ablation_rows),
                "eval_cases": len(eval_cases),
                "used_roulettes": len(histories),
                "discarded_roulettes": len(discarded_roulettes),
            },
            ensure_ascii=True,
        )
    )


if __name__ == "__main__":
    main()

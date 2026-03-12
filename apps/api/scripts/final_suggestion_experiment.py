from __future__ import annotations

import argparse
import asyncio
import json
import random
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
APPS_ROOT = REPO_ROOT / "apps"
if str(APPS_ROOT) not in sys.path:
    sys.path.insert(0, str(APPS_ROOT))

from api.routes.patterns import FinalSuggestionRequest
from api.patterns.engine import pattern_engine
from api.patterns.final_suggestion import (
    build_base_suggestion,
    build_final_suggestion,
    build_focus_context,
    build_runtime_overrides,
    compute_confidence,
    normalize_weights,
)

ATTEMPTS = [1, 2, 3, 4]
THRESHOLDS = [40, 50, 60, 70, 80]


@dataclass
class ReplayCase:
    history: List[int]
    from_index: int


@dataclass
class VariantConfig:
    key: str
    label: str
    preserve_score_ranking: bool
    keep_base_ranking_for_engine: bool


VARIANTS_BASE: List[VariantConfig] = [
    VariantConfig(
        key="A_current",
        label="A (current)",
        preserve_score_ranking=False,
        keep_base_ranking_for_engine=False,
    ),
    VariantConfig(
        key="B_rank_preserved",
        label="B (rank_preserved)",
        preserve_score_ranking=True,
        keep_base_ranking_for_engine=False,
    ),
]

VARIANT_C = VariantConfig(
    key="C_experimental_engine_rank",
    label="C (experimental_engine_rank)",
    preserve_score_ranking=True,
    keep_base_ranking_for_engine=True,
)


def _safe_div(num: float, den: float) -> float:
    if den <= 0:
        return 0.0
    return num / den


def _sanitize_history(raw: Any) -> List[int]:
    if not isinstance(raw, list):
        return []
    out: List[int] = []
    for item in raw:
        try:
            n = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= n <= 36:
            out.append(n)
    return out


def _load_histories(dataset_path: Path) -> List[List[int]]:
    raw = json.loads(dataset_path.read_text(encoding="utf-8"))
    histories: List[List[int]] = []

    if isinstance(raw, list) and raw and all(isinstance(x, int) for x in raw):
        h = _sanitize_history(raw)
        if h:
            histories.append(h)
        return histories

    if not isinstance(raw, list):
        return histories

    for item in raw:
        if not isinstance(item, dict):
            continue
        history = _sanitize_history(item.get("history"))
        if not history:
            history = _sanitize_history(item.get("snapshot"))
        if history:
            histories.append(history)
    return histories


def _build_all_cases(histories: List[List[int]], min_history: int) -> List[ReplayCase]:
    cases: List[ReplayCase] = []
    for history in histories:
        if len(history) < min_history:
            continue
        for idx in range(4, len(history)):
            cases.append(ReplayCase(history=history, from_index=idx))
    return cases


def _sample_cases(all_cases: List[ReplayCase], sample_size: int, seed: int) -> List[ReplayCase]:
    if sample_size >= len(all_cases):
        return list(all_cases)
    rng = random.Random(seed)
    shuffled = list(all_cases)
    rng.shuffle(shuffled)
    return shuffled[:sample_size]


def _conf_bucket(score: int) -> str:
    score = max(0, min(100, int(score)))
    start = (score // 10) * 10
    end = min(100, start + 9)
    return f"{start:02d}-{end:02d}"


def _hit_within_attempts(history: List[int], from_index: int, suggestion: List[int], attempts: int) -> bool:
    if from_index <= 0 or not suggestion:
        return False
    suggestion_set = set(int(n) for n in suggestion)
    for step in range(1, attempts + 1):
        look_idx = from_index - step
        if look_idx < 0:
            break
        if int(history[look_idx]) in suggestion_set:
            return True
    return False


def _parse_optimized_suggestion_sorted(optimized_result: Dict[str, Any]) -> List[int]:
    parsed: List[int] = []
    for raw_n in optimized_result.get("suggestion", []) or []:
        try:
            n = int(raw_n)
        except (TypeError, ValueError):
            continue
        if 0 <= n <= 36:
            parsed.append(n)
    return parsed


def _build_ranked_optimized_list(number_details: Any, fallback: List[int]) -> List[int]:
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


async def _compute_variant_final_suggestion(
    payload: FinalSuggestionRequest,
    *,
    preserve_score_ranking: bool,
    keep_base_ranking_for_engine: bool,
) -> Dict[str, Any]:
    normalized_history = [int(n) for n in payload.history if 0 <= int(n) <= 36]
    if len(normalized_history) < 2:
        return {
            "available": False,
            "list": [],
            "confidence": {"score": 0, "label": "Baixa"},
        }

    from_index = max(0, min(int(payload.from_index), len(normalized_history) - 1))
    focus_number = payload.focus_number
    if focus_number is None:
        focus_number = normalized_history[from_index]
    if not (0 <= int(focus_number) <= 36):
        focus_number = normalized_history[from_index]
    focus_number = int(focus_number)

    target_size = max(1, min(37, int(payload.max_numbers)))
    optimized_max_numbers = max(1, min(37, int(payload.optimized_max_numbers)))
    final_base_weight, final_optimized_weight = normalize_weights(payload.base_weight, payload.optimized_weight)

    siege_window = max(2, min(20, int(payload.siege_window)))
    siege_min_occurrences = max(1, min(10, int(payload.siege_min_occurrences)))
    siege_min_streak = max(1, min(10, int(payload.siege_min_streak)))
    siege_veto_relief = max(0.0, min(1.0, float(payload.siege_veto_relief)))
    inversion_enabled = bool(payload.inversion_enabled)
    inversion_context_window = max(5, min(50, int(payload.inversion_context_window)))
    inversion_penalty_factor = max(0.0, min(1.0, float(payload.inversion_penalty_factor)))

    focus_context = build_focus_context(
        history=normalized_history,
        focus_number=focus_number,
        from_index=from_index,
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
        from_index=from_index,
        siege_window=siege_window,
        siege_min_occurrences=siege_min_occurrences,
        siege_min_streak=siege_min_streak,
        siege_veto_relief=siege_veto_relief,
        preserve_ranking=preserve_score_ranking,
    )

    runtime_overrides = build_runtime_overrides(
        runtime_overrides=payload.runtime_overrides,
        siege_window=siege_window,
        siege_min_occurrences=siege_min_occurrences,
        siege_min_streak=siege_min_streak,
    )

    base_list_for_engine = list(base_list_ranked) if keep_base_ranking_for_engine else sorted(base_list_ranked)
    optimized_result = pattern_engine.evaluate(
        history=normalized_history,
        base_suggestion=base_list_for_engine,
        focus_number=focus_number,
        from_index=from_index,
        max_numbers=optimized_max_numbers,
        runtime_overrides=runtime_overrides,
    )

    opt_list_sorted = _parse_optimized_suggestion_sorted(optimized_result)
    opt_confidence = int(optimized_result.get("confidence", {}).get("score", 0) or 0)
    number_details = optimized_result.get("number_details", [])
    opt_list_ranked = _build_ranked_optimized_list(number_details, opt_list_sorted)

    final_result = build_final_suggestion(
        base_list=base_list_ranked if preserve_score_ranking else base_list_for_engine,
        optimized_list=opt_list_ranked if preserve_score_ranking else opt_list_sorted,
        optimized_confidence=opt_confidence,
        number_details=number_details if isinstance(number_details, list) else [],
        base_confidence_score=base_confidence_score,
        max_size=target_size,
        history_arr=normalized_history,
        from_index=from_index,
        pulled_counts=pulled_counts,
        base_weight=final_base_weight,
        optimized_weight=final_optimized_weight,
        inversion_enabled=inversion_enabled,
        inversion_context_window=inversion_context_window,
        inversion_penalty_factor=inversion_penalty_factor,
    )
    return final_result if isinstance(final_result, dict) else {"available": False, "list": []}


async def _evaluate_case(
    case: ReplayCase,
    *,
    variant: VariantConfig,
    max_numbers: int,
    base_weight: float,
    optimized_weight: float,
) -> Dict[str, Any]:
    payload = FinalSuggestionRequest(
        history=case.history,
        from_index=case.from_index,
        max_numbers=max_numbers,
        optimized_max_numbers=max_numbers,
        base_weight=base_weight,
        optimized_weight=optimized_weight,
    )
    result = await _compute_variant_final_suggestion(
        payload,
        preserve_score_ranking=variant.preserve_score_ranking,
        keep_base_ranking_for_engine=variant.keep_base_ranking_for_engine,
    )

    suggestion = [int(n) for n in (result.get("list") or []) if str(n).isdigit()]
    available = bool(result.get("available", False)) and bool(suggestion)

    confidence = None
    list_size = 0
    hit_flags = {k: False for k in ATTEMPTS}

    if available:
        confidence = int((result.get("confidence") or {}).get("score", 0) or 0)
        list_size = len(suggestion)
        for k in ATTEMPTS:
            hit_flags[k] = _hit_within_attempts(case.history, case.from_index, suggestion, k)

    return {
        "available": available,
        "confidence": confidence,
        "list_size": list_size,
        "hits": hit_flags,
    }


def _build_global_metrics(outcomes: List[Dict[str, Any]], total_cases: int, max_numbers: int) -> Dict[str, Any]:
    available_outcomes = [o for o in outcomes if o["available"]]
    available = len(available_outcomes)
    list_sizes = [int(o["list_size"]) for o in available_outcomes]
    confidence_scores = [int(o["confidence"]) for o in available_outcomes if o["confidence"] is not None]

    hits_by_k = {k: 0 for k in ATTEMPTS}
    for o in available_outcomes:
        for k in ATTEMPTS:
            if bool(o["hits"][k]):
                hits_by_k[k] += 1

    confidence_dist: Dict[str, int] = {}
    for score in confidence_scores:
        b = _conf_bucket(score)
        confidence_dist[b] = confidence_dist.get(b, 0) + 1

    conditional = {f"hit@{k}": round(_safe_div(hits_by_k[k], available), 6) for k in ATTEMPTS}
    effective = {f"hit@{k}": round(_safe_div(hits_by_k[k], total_cases), 6) for k in ATTEMPTS}

    return {
        "eligible_cases": total_cases,
        "available_cases": available,
        "coverage": round(_safe_div(available, total_cases), 6),
        "average_list_size": round(mean(list_sizes), 6) if list_sizes else 0.0,
        "average_list_size_all_cases": round(_safe_div(sum(list_sizes), total_cases), 6),
        "oversize_lists": sum(1 for n in list_sizes if n > max_numbers),
        "confidence_distribution": dict(sorted(confidence_dist.items(), key=lambda kv: kv[0])),
        "confidence_mean": round(mean(confidence_scores), 6) if confidence_scores else 0.0,
        "conditional_hits": conditional,
        "effective_hits": effective,
    }


def _build_bucket_metrics(outcomes: List[Dict[str, Any]], total_cases: int) -> Dict[str, Any]:
    bucket_data: Dict[str, Dict[str, Any]] = {}

    for o in outcomes:
        if not o["available"]:
            continue
        score = o["confidence"]
        if score is None:
            continue
        bucket = _conf_bucket(int(score))
        if bucket not in bucket_data:
            bucket_data[bucket] = {
                "available_cases": 0,
                "confidence_sum": 0,
                "list_size_sum": 0,
                "hits": {k: 0 for k in ATTEMPTS},
            }
        row = bucket_data[bucket]
        row["available_cases"] += 1
        row["confidence_sum"] += int(score)
        row["list_size_sum"] += int(o["list_size"])
        for k in ATTEMPTS:
            if bool(o["hits"][k]):
                row["hits"][k] += 1

    built: Dict[str, Any] = {}
    for bucket, row in sorted(bucket_data.items(), key=lambda kv: kv[0]):
        available = int(row["available_cases"])
        avg_conf = _safe_div(float(row["confidence_sum"]), available)
        avg_size = _safe_div(float(row["list_size_sum"]), available)
        hits = row["hits"]

        conditional = {f"hit@{k}": round(_safe_div(hits[k], available), 6) for k in ATTEMPTS}
        effective = {f"hit@{k}": round(_safe_div(hits[k], total_cases), 6) for k in ATTEMPTS}

        built[bucket] = {
            "available_cases": available,
            "coverage_total": round(_safe_div(available, total_cases), 6),
            "confidence_mean": round(avg_conf, 6),
            "average_list_size": round(avg_size, 6),
            "hits_abs": {f"hit@{k}": int(hits[k]) for k in ATTEMPTS},
            "conditional_hits": conditional,
            "effective_hits": effective,
        }
    return built


def _build_threshold_metrics(outcomes: List[Dict[str, Any]], total_cases: int, thresholds: List[int]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for th in thresholds:
        selected = [o for o in outcomes if o["available"] and o["confidence"] is not None and int(o["confidence"]) >= th]
        selected_count = len(selected)
        hits_abs = {k: 0 for k in ATTEMPTS}
        list_sizes = [int(o["list_size"]) for o in selected]

        for o in selected:
            for k in ATTEMPTS:
                if bool(o["hits"][k]):
                    hits_abs[k] += 1

        conditional = {f"hit@{k}": round(_safe_div(hits_abs[k], selected_count), 6) for k in ATTEMPTS}
        effective = {f"hit@{k}": round(_safe_div(hits_abs[k], total_cases), 6) for k in ATTEMPTS}

        out[f">={th}"] = {
            "threshold": th,
            "selected_cases": selected_count,
            "eligible_cases": total_cases,
            "coverage": round(_safe_div(selected_count, total_cases), 6),
            "average_list_size": round(mean(list_sizes), 6) if list_sizes else 0.0,
            "hits_abs": {f"hit@{k}": int(hits_abs[k]) for k in ATTEMPTS},
            "conditional_hits": conditional,
            "effective_hits": effective,
        }
    return out


def _build_calibration_metrics(bucket_metrics: Dict[str, Any], available_cases: int) -> Dict[str, Any]:
    if available_cases <= 0:
        return {
            "ece_hit@4": 0.0,
            "ece_hit@1": 0.0,
            "available_cases": 0,
            "monotonic_pairs": 0,
            "monotonic_non_decrease_ratio_hit@4": 0.0,
        }

    ece4 = 0.0
    ece1 = 0.0
    ordered = sorted(bucket_metrics.items(), key=lambda kv: kv[0])

    prev_h4 = None
    monotonic_pairs = 0
    monotonic_non_decrease = 0

    for _, row in ordered:
        count = int(row["available_cases"])
        weight = _safe_div(count, available_cases)
        conf_prob = float(row["confidence_mean"]) / 100.0
        obs4 = float((row["conditional_hits"] or {}).get("hit@4", 0.0))
        obs1 = float((row["conditional_hits"] or {}).get("hit@1", 0.0))

        ece4 += weight * abs(obs4 - conf_prob)
        ece1 += weight * abs(obs1 - conf_prob)

        if prev_h4 is not None:
            monotonic_pairs += 1
            if obs4 >= prev_h4:
                monotonic_non_decrease += 1
        prev_h4 = obs4

    return {
        "ece_hit@4": round(ece4, 6),
        "ece_hit@1": round(ece1, 6),
        "available_cases": available_cases,
        "monotonic_pairs": monotonic_pairs,
        "monotonic_non_decrease_ratio_hit@4": round(_safe_div(monotonic_non_decrease, monotonic_pairs), 6),
    }


def _delta(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "coverage_delta": round(float(b.get("coverage", 0.0)) - float(a.get("coverage", 0.0)), 6),
        "average_list_size_delta": round(
            float(b.get("average_list_size", 0.0)) - float(a.get("average_list_size", 0.0)),
            6,
        ),
        "effective_hit@4_delta": round(
            float((b.get("effective_hits") or {}).get("hit@4", 0.0))
            - float((a.get("effective_hits") or {}).get("hit@4", 0.0)),
            6,
        ),
        "conditional_hit@4_delta": round(
            float((b.get("conditional_hits") or {}).get("hit@4", 0.0))
            - float((a.get("conditional_hits") or {}).get("hit@4", 0.0)),
            6,
        ),
    }


async def _run_variant(
    cases: List[ReplayCase],
    *,
    variant: VariantConfig,
    max_numbers: int,
    base_weight: float,
    optimized_weight: float,
) -> Dict[str, Any]:
    outcomes: List[Dict[str, Any]] = []
    start = time.perf_counter()

    for case in cases:
        outcomes.append(
            await _evaluate_case(
                case,
                variant=variant,
                max_numbers=max_numbers,
                base_weight=base_weight,
                optimized_weight=optimized_weight,
            )
        )

    total = len(cases)
    global_metrics = _build_global_metrics(outcomes, total, max_numbers)
    bucket_metrics = _build_bucket_metrics(outcomes, total)
    threshold_metrics = _build_threshold_metrics(outcomes, total, THRESHOLDS)
    calibration = _build_calibration_metrics(bucket_metrics, int(global_metrics["available_cases"]))

    elapsed = time.perf_counter() - start

    return {
        "variant": variant.key,
        "label": variant.label,
        "runtime_seconds": round(elapsed, 3),
        "metrics": global_metrics,
        "confidence_buckets": bucket_metrics,
        "confidence_thresholds": threshold_metrics,
        "calibration": calibration,
    }


async def _run_sample(
    sample_cases: List[ReplayCase],
    *,
    variants: List[VariantConfig],
    max_numbers: int,
    base_weight: float,
    optimized_weight: float,
) -> Dict[str, Any]:
    variant_reports: Dict[str, Any] = {}
    for variant in variants:
        variant_reports[variant.key] = await _run_variant(
            sample_cases,
            variant=variant,
            max_numbers=max_numbers,
            base_weight=base_weight,
            optimized_weight=optimized_weight,
        )

    comparisons: Dict[str, Any] = {}
    baseline = variant_reports.get("A_current", {}).get("metrics", {})
    for key, report in variant_reports.items():
        if key == "A_current":
            continue
        comparisons[f"{key}_minus_A_current"] = _delta(baseline, report.get("metrics", {}))

    return {
        "cases": len(sample_cases),
        "variant_reports": variant_reports,
        "comparisons": comparisons,
    }


def _estimate_runtime_seconds(cases: int, variants: int, eval_time_sec: float) -> float:
    return float(cases) * float(variants) * float(eval_time_sec)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ampliação de experimento final-suggestion com análise de confiança.")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=REPO_ROOT / "apps" / "signals" / "helpers" / "results.json",
        help="Arquivo JSON com histórico(s) para replay.",
    )
    parser.add_argument("--min-history", type=int, default=12)
    parser.add_argument("--max-numbers", type=int, default=11)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--include-variant-c", action="store_true", default=True)
    parser.add_argument("--disable-variant-c", action="store_true", default=False)
    parser.add_argument("--include-full", action="store_true", default=True)
    parser.add_argument("--disable-full", action="store_true", default=False)
    parser.add_argument("--time-budget-sec", type=int, default=1800)
    parser.add_argument("--base-weight", type=float, default=0.4)
    parser.add_argument("--optimized-weight", type=float, default=0.6)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "docs" / "final-suggestion-confidence-analysis.json",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()

    include_c = bool(args.include_variant_c) and not bool(args.disable_variant_c)
    include_full = bool(args.include_full) and not bool(args.disable_full)

    variants = list(VARIANTS_BASE)
    if include_c:
        variants.append(VARIANT_C)

    histories = _load_histories(args.dataset)
    all_cases = _build_all_cases(histories, min_history=max(6, int(args.min_history)))
    rng_seed = int(args.seed)

    max_numbers = max(1, min(37, int(args.max_numbers)))
    base_weight = float(args.base_weight)
    optimized_weight = float(args.optimized_weight)

    requested_sizes = [200, 500, 1000]
    samples: Dict[str, Any] = {}

    t0 = time.perf_counter()
    eval_time_hint = 0.03

    for size in requested_sizes:
        sample_size = min(size, len(all_cases))
        sample_cases = _sample_cases(all_cases, sample_size, seed=rng_seed + size)
        sample_report = await _run_sample(
            sample_cases,
            variants=variants,
            max_numbers=max_numbers,
            base_weight=base_weight,
            optimized_weight=optimized_weight,
        )
        samples[str(size)] = sample_report

        total_runtime = 0.0
        count_runtime = 0
        for vr in sample_report["variant_reports"].values():
            total_runtime += float(vr.get("runtime_seconds", 0.0))
            count_runtime += 1
        if count_runtime > 0 and sample_size > 0:
            eval_time_hint = max(eval_time_hint, (total_runtime / count_runtime) / sample_size)

    full_info: Dict[str, Any] = {"requested": include_full, "ran": False}
    if include_full:
        remaining_budget = max(0.0, float(args.time_budget_sec) - (time.perf_counter() - t0))
        full_variant_count = len(VARIANTS_BASE)
        estimated = _estimate_runtime_seconds(len(all_cases), full_variant_count, eval_time_hint)

        full_info["estimated_seconds"] = round(estimated, 3)
        full_info["remaining_budget_seconds"] = round(remaining_budget, 3)

        if estimated <= remaining_budget and len(all_cases) > 0:
            full_cases = list(all_cases)
            full_variants = list(VARIANTS_BASE)
            full_report = await _run_sample(
                full_cases,
                variants=full_variants,
                max_numbers=max_numbers,
                base_weight=base_weight,
                optimized_weight=optimized_weight,
            )
            samples["full"] = full_report
            full_info["ran"] = True
            full_info["reason"] = "executed"
        else:
            full_info["ran"] = False
            full_info["reason"] = "not_viable_within_time_budget"
            full_info["cases_available"] = len(all_cases)

    report = {
        "meta": {
            "dataset": str(args.dataset),
            "histories_loaded": len(histories),
            "all_cases_available": len(all_cases),
            "max_numbers": max_numbers,
            "attempts": ATTEMPTS,
            "thresholds": THRESHOLDS,
            "seed": rng_seed,
            "variants": [v.key for v in variants],
            "production_variant": "B_rank_preserved",
            "variant_c_isolated_experimental": include_c,
            "full_execution": full_info,
        },
        "samples": samples,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "samples": list(samples.keys())}, ensure_ascii=True))


if __name__ == "__main__":
    asyncio.run(main())

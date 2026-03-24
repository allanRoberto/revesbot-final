from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
import random
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
APPS_ROOT = REPO_ROOT / "apps"
if str(APPS_ROOT) not in sys.path:
    sys.path.insert(0, str(APPS_ROOT))

from api.patterns.engine import pattern_engine

ATTEMPTS = [1, 2, 4, 8, 10]
THRESHOLDS = [40, 50, 60, 70]


@dataclass
class HistorySource:
    key: str
    label: str
    history: List[int]
    meta: Dict[str, Any]


@dataclass
class ReplayCase:
    source_key: str
    history: List[int]
    from_index: int


def _safe_div(num: float, den: float) -> float:
    if den <= 0:
        return 0.0
    return num / den


def _bucket(score: int | float) -> str:
    safe_score = max(0, min(100, int(round(float(score)))))
    start = (safe_score // 10) * 10
    end = min(100, start + 9)
    return f"{start:02d}-{end:02d}"


def _normalize_history(raw: Any) -> List[int]:
    if not isinstance(raw, list):
        return []
    out: List[int] = []
    for item in raw:
        try:
            num = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= num <= 36:
            out.append(num)
    return out


def _load_snapshot_cache(snapshot_dir: Path) -> List[HistorySource]:
    sources: List[HistorySource] = []
    for path in sorted(snapshot_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        history = _normalize_history(payload.get("history"))
        if not history:
            history = _normalize_history(payload.get("results"))
        if len(history) < 30:
            continue
        source_key = f"snapshot:{path.stem}"
        sources.append(
            HistorySource(
                key=source_key,
                label=str(payload.get("slug") or path.stem),
                history=history,
                meta={
                    "source_type": "snapshot_cache",
                    "path": str(path),
                    "timestamp": payload.get("timestamp"),
                    "count": payload.get("count"),
                    "slug": payload.get("slug"),
                },
            )
        )
    return sources


def _http_json(url: str, timeout_sec: float) -> Any:
    with urllib.request.urlopen(url, timeout=timeout_sec) as response:
        return json.loads(response.read().decode("utf-8"))


def _load_api_histories(base_url: str, slugs: Sequence[str], limit: int, timeout_sec: float) -> List[HistorySource]:
    sources: List[HistorySource] = []
    resolved_slugs = list(slugs)
    if not resolved_slugs:
        payload = _http_json(f"{base_url.rstrip('/')}/api/roulettes-list", timeout_sec)
        if isinstance(payload, list):
            resolved_slugs = [str(item.get("id", "")).strip() for item in payload if isinstance(item, dict)]
    for slug in resolved_slugs:
        if not slug:
            continue
        encoded = urllib.parse.quote(slug, safe="")
        payload = _http_json(f"{base_url.rstrip('/')}/history/{encoded}?limit={max(1, limit)}", timeout_sec)
        history = _normalize_history(payload.get("results", []) if isinstance(payload, dict) else payload)
        if len(history) < 30:
            continue
        sources.append(
            HistorySource(
                key=f"api:{slug}",
                label=slug,
                history=history,
                meta={
                    "source_type": "api_history",
                    "base_url": base_url,
                    "slug": slug,
                    "limit": limit,
                },
            )
        )
    return sources


def _load_mongo_histories(mongo_url: str, slugs: Sequence[str], limit: int) -> List[HistorySource]:
    from pymongo import MongoClient

    client = MongoClient(mongo_url, tls=True)
    coll = client["roleta_db"]["history"]
    resolved_slugs = list(slugs)
    if not resolved_slugs:
        resolved_slugs = sorted(str(item) for item in coll.distinct("roulette_id"))

    sources: List[HistorySource] = []
    for slug in resolved_slugs:
        cursor = coll.find({"roulette_id": slug}).sort("timestamp", -1).limit(max(1, limit))
        history = _normalize_history([row.get("value") for row in cursor])
        if len(history) < 30:
            continue
        sources.append(
            HistorySource(
                key=f"mongo:{slug}",
                label=slug,
                history=history,
                meta={
                    "source_type": "mongo_history",
                    "slug": slug,
                    "limit": limit,
                },
            )
        )
    client.close()
    return sources


def _build_cases(
    sources: Sequence[HistorySource],
    *,
    attempts: int,
    max_cases_per_source: int,
    seed: int,
) -> List[ReplayCase]:
    rng = random.Random(seed)
    cases: List[ReplayCase] = []
    for source in sources:
        local = [
            ReplayCase(source_key=source.key, history=source.history, from_index=idx)
            for idx in range(max(4, attempts), len(source.history))
        ]
        if max_cases_per_source > 0 and len(local) > max_cases_per_source:
            rng.shuffle(local)
            local = local[:max_cases_per_source]
        cases.extend(local)
    rng.shuffle(cases)
    return cases


def _hit_within_attempts(history: List[int], from_index: int, suggestion: List[int], attempts: int) -> bool:
    if not suggestion or from_index <= 0:
        return False
    suggestion_set = set(int(n) for n in suggestion)
    for step in range(1, attempts + 1):
        look_idx = from_index - step
        if look_idx < 0:
            break
        if int(history[look_idx]) in suggestion_set:
            return True
    return False


def _build_bucket_rows(outcomes: List[Dict[str, Any]], eligible_cases: int) -> Dict[str, Any]:
    rows: Dict[str, Dict[str, Any]] = {}
    for outcome in outcomes:
        if not outcome["available"]:
            continue
        label = _bucket(outcome["score"])
        row = rows.setdefault(
            label,
            {
                "available_cases": 0,
                "scores": [],
                "list_sizes": [],
                "hits_abs": {f"hit@{k}": 0 for k in ATTEMPTS},
            },
        )
        row["available_cases"] += 1
        row["scores"].append(int(outcome["score"]))
        row["list_sizes"].append(int(outcome["list_size"]))
        for attempt in ATTEMPTS:
            if outcome[f"hit@{attempt}"]:
                row["hits_abs"][f"hit@{attempt}"] += 1

    out: Dict[str, Any] = {}
    for label, row in sorted(rows.items(), key=lambda kv: kv[0]):
        available = int(row["available_cases"])
        conditional = {}
        effective = {}
        for attempt in ATTEMPTS:
            hits = int(row["hits_abs"][f"hit@{attempt}"])
            conditional[f"hit@{attempt}"] = round(_safe_div(hits, available), 6)
            effective[f"hit@{attempt}"] = round(_safe_div(hits, eligible_cases), 6)
        out[label] = {
            "available_cases": available,
            "coverage_total": round(_safe_div(available, eligible_cases), 6),
            "confidence_mean": round(mean(row["scores"]), 6) if row["scores"] else 0.0,
            "average_list_size": round(mean(row["list_sizes"]), 6) if row["list_sizes"] else 0.0,
            "hits_abs": {k: int(v) for k, v in row["hits_abs"].items()},
            "conditional_hits": conditional,
            "effective_hits": effective,
        }
    return out


def _build_threshold_rows(outcomes: List[Dict[str, Any]], eligible_cases: int) -> Dict[str, Any]:
    rows: Dict[str, Any] = {}
    for threshold in THRESHOLDS:
        selected = [row for row in outcomes if row["available"] and int(row["score"]) >= threshold]
        hits_abs = {f"hit@{k}": 0 for k in ATTEMPTS}
        list_sizes: List[int] = []
        for row in selected:
            list_sizes.append(int(row["list_size"]))
            for attempt in ATTEMPTS:
                if row[f"hit@{attempt}"]:
                    hits_abs[f"hit@{attempt}"] += 1
        selected_cases = len(selected)
        conditional = {}
        effective = {}
        for attempt in ATTEMPTS:
            hits = hits_abs[f"hit@{attempt}"]
            conditional[f"hit@{attempt}"] = round(_safe_div(hits, selected_cases), 6)
            effective[f"hit@{attempt}"] = round(_safe_div(hits, eligible_cases), 6)
        rows[f">={threshold}"] = {
            "threshold": threshold,
            "selected_cases": selected_cases,
            "eligible_cases": eligible_cases,
            "coverage": round(_safe_div(selected_cases, eligible_cases), 6),
            "average_list_size": round(mean(list_sizes), 6) if list_sizes else 0.0,
            "hits_abs": {k: int(v) for k, v in hits_abs.items()},
            "conditional_hits": conditional,
            "effective_hits": effective,
        }
    return rows


def _build_calibration_metrics(bucket_rows: Mapping[str, Any], available_cases: int) -> Dict[str, Any]:
    if available_cases <= 0:
        return {
            "ece_hit@4": 0.0,
            "available_cases": 0,
            "monotonic_pairs": 0,
            "monotonic_non_decrease_ratio_hit@4": 0.0,
        }
    ece4 = 0.0
    prev_h4 = None
    monotonic_pairs = 0
    monotonic_non_decrease = 0
    for _, row in sorted(bucket_rows.items(), key=lambda kv: kv[0]):
        count = int(row["available_cases"])
        weight = _safe_div(count, available_cases)
        conf_prob = float(row["confidence_mean"]) / 100.0
        obs4 = float((row["conditional_hits"] or {}).get("hit@4", 0.0))
        ece4 += weight * abs(obs4 - conf_prob)
        if prev_h4 is not None:
            monotonic_pairs += 1
            if obs4 >= prev_h4:
                monotonic_non_decrease += 1
        prev_h4 = obs4
    return {
        "ece_hit@4": round(ece4, 6),
        "available_cases": available_cases,
        "monotonic_pairs": monotonic_pairs,
        "monotonic_non_decrease_ratio_hit@4": round(_safe_div(monotonic_non_decrease, monotonic_pairs), 6),
    }


def _build_variant_report(outcomes: List[Dict[str, Any]], eligible_cases: int) -> Dict[str, Any]:
    available = [row for row in outcomes if row["available"]]
    list_sizes = [int(row["list_size"]) for row in available]
    confidence_scores = [int(row["score"]) for row in available]
    hits_abs = {f"hit@{k}": 0 for k in ATTEMPTS}
    for row in available:
        for attempt in ATTEMPTS:
            if row[f"hit@{attempt}"]:
                hits_abs[f"hit@{attempt}"] += 1
    conditional = {
        f"hit@{attempt}": round(_safe_div(hits_abs[f"hit@{attempt}"], len(available)), 6)
        for attempt in ATTEMPTS
    }
    effective = {
        f"hit@{attempt}": round(_safe_div(hits_abs[f"hit@{attempt}"], eligible_cases), 6)
        for attempt in ATTEMPTS
    }
    confidence_distribution: Dict[str, int] = {}
    for score in confidence_scores:
        label = _bucket(score)
        confidence_distribution[label] = confidence_distribution.get(label, 0) + 1
    bucket_rows = _build_bucket_rows(outcomes, eligible_cases)
    return {
        "metrics": {
            "eligible_cases": eligible_cases,
            "available_cases": len(available),
            "coverage": round(_safe_div(len(available), eligible_cases), 6),
            "average_list_size": round(mean(list_sizes), 6) if list_sizes else 0.0,
            "confidence_distribution": dict(sorted(confidence_distribution.items(), key=lambda kv: kv[0])),
            "confidence_mean": round(mean(confidence_scores), 6) if confidence_scores else 0.0,
            "conditional_hits": conditional,
            "effective_hits": effective,
        },
        "confidence_buckets": bucket_rows,
        "confidence_thresholds": _build_threshold_rows(outcomes, eligible_cases),
        "calibration": _build_calibration_metrics(bucket_rows, len(available)),
    }


def _build_bucket_calibration_from_outcomes(
    outcomes: List[Dict[str, Any]],
    *,
    bucket_signal_target: int,
) -> Dict[str, Any]:
    rows: Dict[str, Dict[str, int]] = {}
    for outcome in outcomes:
        if not outcome["available"]:
            continue
        label = _bucket(outcome["merged_raw_v2"])
        row = rows.setdefault(
            label,
            {
                "signals": 0,
                "hits": {f"hit@{attempt}": 0 for attempt in ATTEMPTS},
                "first_hit_counts": {
                    "hit@1": 0,
                    "hit@2": 0,
                    "hit@4": 0,
                    "hit@8": 0,
                    "hit@10": 0,
                },
                "first_hit_attempts_sum": 0,
                "first_hit_attempts_count": 0,
            },
        )
        row["signals"] += 1
        for attempt in ATTEMPTS:
            if outcome[f"hit@{attempt}"]:
                row["hits"][f"hit@{attempt}"] += 1
        first_hit_attempt = None
        if outcome["hit@1"]:
            row["first_hit_counts"]["hit@1"] += 1
            first_hit_attempt = 1
        elif outcome["hit@2"]:
            row["first_hit_counts"]["hit@2"] += 1
            first_hit_attempt = 2
        elif outcome["hit@4"]:
            row["first_hit_counts"]["hit@4"] += 1
            first_hit_attempt = 4
        elif outcome["hit@8"]:
            row["first_hit_counts"]["hit@8"] += 1
            first_hit_attempt = 8
        elif outcome["hit@10"]:
            row["first_hit_counts"]["hit@10"] += 1
            first_hit_attempt = 10
        if first_hit_attempt is not None:
            row["first_hit_attempts_sum"] += int(first_hit_attempt)
            row["first_hit_attempts_count"] += 1

    buckets: Dict[str, Any] = {}
    for label, row in sorted(rows.items(), key=lambda kv: kv[0]):
        signals = int(row["signals"])
        hit_rates = {
            f"hit@{attempt}": round(_safe_div(int(row["hits"][f"hit@{attempt}"]), signals), 6)
            for attempt in ATTEMPTS
        }
        hit_rate = float(hit_rates["hit@4"])
        reliability = min(1.0, _safe_div(signals, bucket_signal_target))
        first_hit_counts = row["first_hit_counts"]
        first_hit_probs = {
            "hit@1": _safe_div(int(first_hit_counts["hit@1"]), signals),
            "hit@2": _safe_div(int(first_hit_counts["hit@2"]), signals),
            "hit@4": _safe_div(int(first_hit_counts["hit@4"]), signals),
            "hit@8": _safe_div(int(first_hit_counts["hit@8"]), signals),
            "hit@10": _safe_div(int(first_hit_counts["hit@10"]), signals),
        }
        avg_first_hit_attempt = (
            round(_safe_div(int(row["first_hit_attempts_sum"]), int(row["first_hit_attempts_count"])), 6)
            if int(row["first_hit_attempts_count"]) > 0
            else None
        )
        latency_health = 0.0
        if avg_first_hit_attempt is not None:
            latency_health = max(0.0, min(1.0, 1.0 - ((float(avg_first_hit_attempt) - 1.0) / 9.0)))
        promptness_score = 100.0 * (
            (first_hit_probs["hit@1"] * 1.00)
            + (first_hit_probs["hit@2"] * 0.90)
            + (first_hit_probs["hit@4"] * 0.68)
            + (first_hit_probs["hit@8"] * 0.28)
            + (first_hit_probs["hit@10"] * 0.12)
        )
        if avg_first_hit_attempt is not None:
            promptness_score = (promptness_score * 0.82) + (latency_health * 18.0)
        buckets[label] = {
            "signals": signals,
            "hit_rate": round(hit_rate, 6),
            "hit@1": hit_rates["hit@1"],
            "hit@2": hit_rates["hit@2"],
            "hit@4": hit_rates["hit@4"],
            "hit@8": hit_rates["hit@8"],
            "hit@10": hit_rates["hit@10"],
            "avg_first_hit_attempt": avg_first_hit_attempt,
            "promptness_score": round(max(0.0, min(100.0, promptness_score)), 6),
            "reliability": round(reliability, 6),
        }
    return buckets


def _apply_shadow_calibration(raw_score: int, buckets: Mapping[str, Any]) -> Dict[str, Any]:
    label = _bucket(raw_score)
    row = buckets.get(label, {}) if isinstance(buckets, Mapping) else {}
    hit_rate = max(0.0, min(1.0, float(row.get("hit_rate", 0.0) or 0.0)))
    promptness_score = max(0.0, min(100.0, float(row.get("promptness_score", hit_rate * 100.0) or (hit_rate * 100.0))))
    reliability = max(0.0, min(1.0, float(row.get("reliability", 0.0) or 0.0)))
    calibrated = float(raw_score)
    if reliability > 0.0:
        calibrated = (float(raw_score) * (1.0 - reliability)) + (promptness_score * reliability)
    return {
        "score": max(0, min(100, int(round(calibrated)))),
        "bucket": label,
        "hit_rate": round(hit_rate, 6),
        "promptness_score": round(promptness_score, 6),
        "reliability": round(reliability, 6),
    }


def _write_markdown(path: Path, payload: Dict[str, Any]) -> None:
    source = payload["source"]
    baseline = payload["variants"]["current_confidence"]
    shadow = payload["variants"]["confidence_v2"]

    def _bucket_lines(rows: Mapping[str, Any]) -> List[str]:
        lines = ["| Bucket | Casos | Coverage | Conditional Hit@4 | Effective Hit@4 |"]
        lines.append("|---|---:|---:|---:|---:|")
        for label, row in rows.items():
            lines.append(
                f"| {label} | {row['available_cases']} | {row['coverage_total']:.3f} | "
                f"{row['conditional_hits']['hit@4']:.6f} | {row['effective_hits']['hit@4']:.3f} |"
            )
        return lines

    def _threshold_lines(rows: Mapping[str, Any]) -> List[str]:
        lines = ["| Threshold | Casos | Coverage | Conditional Hit@4 | Effective Hit@4 |"]
        lines.append("|---|---:|---:|---:|---:|")
        for label, row in rows.items():
            lines.append(
                f"| {label} | {row['selected_cases']} | {row['coverage']:.3f} | "
                f"{row['conditional_hits']['hit@4']:.6f} | {row['effective_hits']['hit@4']:.3f} |"
            )
        return lines

    lines = [
        "# Confidence V2 Analysis",
        "",
        f"Generated at: {payload['generated_at']}",
        f"Source mode: `{source['mode']}`",
        f"Eligible cases: `{payload['eligible_cases']}`",
        "",
        "## Source",
        f"- source type: `{source['mode']}`",
        f"- histories used: `{source['histories_used']}`",
        f"- details: `{source['details']}`",
        f"- calibration cases: `{source['calibration_cases']}`",
        f"- evaluation cases: `{source['evaluation_cases']}`",
        "",
        "## Baseline vs V2",
        f"- current coverage: `{baseline['metrics']['coverage']}`",
        f"- current conditional_hit@4: `{baseline['metrics']['conditional_hits']['hit@4']}`",
        f"- current effective_hit@4: `{baseline['metrics']['effective_hits']['hit@4']}`",
        f"- current ECE hit@4: `{baseline['calibration']['ece_hit@4']}`",
        f"- v2 coverage: `{shadow['metrics']['coverage']}`",
        f"- v2 conditional_hit@4: `{shadow['metrics']['conditional_hits']['hit@4']}`",
        f"- v2 effective_hit@4: `{shadow['metrics']['effective_hits']['hit@4']}`",
        f"- v2 ECE hit@4: `{shadow['calibration']['ece_hit@4']}`",
        "",
        "## Current Confidence Buckets",
        *_bucket_lines(baseline["confidence_buckets"]),
        "",
        "## V2 Confidence Buckets",
        *_bucket_lines(shadow["confidence_buckets"]),
        "",
        "## Current Threshold Coverage",
        *_threshold_lines(baseline["confidence_thresholds"]),
        "",
        "## V2 Threshold Coverage",
        *_threshold_lines(shadow["confidence_thresholds"]),
        "",
        "## Calibration Notes",
        "- `confidence_v2` permanece em shadow mode.",
        "- `confidence` atual continua sendo a score operacional de produção.",
        "- A calibracao v2 usa bucket de `merged_raw_v2` com shrinkage por volume do bucket.",
        "- A pontuacao calibrada prioriza buckets com acerto mais cedo (`hit@1`, `hit@2`) e penaliza buckets com primeiro hit tardio.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_calibration_config(
    buckets: Mapping[str, Any],
    *,
    source_mode: str,
    source_details: Mapping[str, Any],
    bucket_signal_target: int,
) -> Dict[str, Any]:
    return {
        "version": "1.0.0",
        "mode": "shadow",
        "description": "Calibracao bucketizada da confidence_v2 baseada em hit rapido e latencia do primeiro acerto.",
        "bucket_signal_target": bucket_signal_target,
        "source": {
            "type": source_mode,
            "details": dict(source_details),
        },
        "buckets": dict(buckets),
    }


def _analyze_cases(
    cases: Iterable[ReplayCase],
    max_numbers: int,
    *,
    bucket_signal_target: int,
    calibration_ratio: float,
) -> Dict[str, Any]:
    base_outcomes: List[Dict[str, Any]] = []
    pattern_engine.clear_cache()
    for case in cases:
        result = pattern_engine.evaluate(
            history=case.history,
            base_suggestion=[],
            focus_number=None,
            from_index=case.from_index,
            max_numbers=max_numbers,
            use_adaptive_weights=False,
        )
        suggestion = [int(n) for n in (result.get("suggestion") or []) if isinstance(n, int) or str(n).isdigit()]
        available = bool(result.get("available", False))
        current_score = int((result.get("confidence") or {}).get("score", 0) or 0)
        breakdown = result.get("confidence_breakdown", {}) if isinstance(result.get("confidence_breakdown"), dict) else {}
        row = {
            "available": available,
            "list_size": len(suggestion),
            "current_score": current_score,
            "merged_raw_v2": int(breakdown.get("merged_raw_v2", 0) or 0),
        }
        for attempt in ATTEMPTS:
            hit = _hit_within_attempts(case.history, case.from_index, suggestion, attempt)
            row[f"hit@{attempt}"] = hit
        base_outcomes.append(row)

    eligible_cases = len(base_outcomes)
    calibration_size = max(1, min(eligible_cases, int(round(eligible_cases * calibration_ratio))))
    if calibration_size >= eligible_cases and eligible_cases > 1:
        calibration_size = eligible_cases - 1
    calibration_cases = base_outcomes[:calibration_size]
    evaluation_cases = base_outcomes[calibration_size:] or list(base_outcomes)
    calibration_buckets = _build_bucket_calibration_from_outcomes(
        calibration_cases,
        bucket_signal_target=bucket_signal_target,
    )

    current_outcomes: List[Dict[str, Any]] = []
    v2_outcomes: List[Dict[str, Any]] = []
    for row in evaluation_cases:
        current_row = {
            "available": row["available"],
            "list_size": row["list_size"],
            "score": row["current_score"],
        }
        calibrated_v2 = _apply_shadow_calibration(int(row["merged_raw_v2"]), calibration_buckets)
        v2_row = {
            "available": row["available"],
            "list_size": row["list_size"],
            "score": int(calibrated_v2["score"]),
        }
        for attempt in ATTEMPTS:
            current_row[f"hit@{attempt}"] = row[f"hit@{attempt}"]
            v2_row[f"hit@{attempt}"] = row[f"hit@{attempt}"]
        current_outcomes.append(current_row)
        v2_outcomes.append(v2_row)

    return {
        "eligible_cases": len(evaluation_cases),
        "calibration_cases": len(calibration_cases),
        "evaluation_cases": len(evaluation_cases),
        "calibration_buckets": calibration_buckets,
        "variants": {
            "current_confidence": _build_variant_report(current_outcomes, len(evaluation_cases)),
            "confidence_v2": _build_variant_report(v2_outcomes, len(evaluation_cases)),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze confidence_v2 shadow calibration.")
    parser.add_argument("--source-mode", choices=["snapshot_cache", "api", "mongo"], default="snapshot_cache")
    parser.add_argument("--snapshot-dir", type=Path, default=REPO_ROOT / "apps" / "signals" / "backup" / "roulette_cache")
    parser.add_argument("--snapshot-derived-from", default="/history/{slug}")
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--mongo-url", default=os.getenv("MONGO_URL") or "")
    parser.add_argument("--slugs", nargs="*", default=[])
    parser.add_argument("--history-limit", type=int, default=2000)
    parser.add_argument("--max-cases-per-source", type=int, default=400)
    parser.add_argument("--max-numbers", type=int, default=11)
    parser.add_argument("--bucket-signal-target", type=int, default=150)
    parser.add_argument("--calibration-ratio", type=float, default=0.6)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--report-out", type=Path, default=REPO_ROOT / "docs" / "confidence-v2-analysis.md")
    parser.add_argument("--config-out", type=Path, default=REPO_ROOT / "apps" / "api" / "config" / "confidence_v2_calibration.json")
    parser.add_argument("--json-out", type=Path, default=REPO_ROOT / "docs" / "confidence-v2-analysis.json")
    parser.add_argument("--timeout-sec", type=float, default=10.0)
    args = parser.parse_args()

    if args.source_mode == "snapshot_cache":
        sources = _load_snapshot_cache(args.snapshot_dir)
        source_details = {
            "snapshot_dir": str(args.snapshot_dir),
            "derived_from": args.snapshot_derived_from,
        }
    elif args.source_mode == "api":
        sources = _load_api_histories(args.base_url, args.slugs, args.history_limit, args.timeout_sec)
        source_details = {"base_url": args.base_url, "slugs": list(args.slugs), "history_limit": args.history_limit}
    else:
        if not args.mongo_url:
            raise RuntimeError("mongo-url is required when source-mode=mongo")
        sources = _load_mongo_histories(args.mongo_url, args.slugs, args.history_limit)
        source_details = {"history_limit": args.history_limit, "slugs": list(args.slugs)}

    if not sources:
        raise RuntimeError("No histories available for confidence_v2 analysis.")

    cases = _build_cases(
        sources,
        attempts=max(ATTEMPTS),
        max_cases_per_source=max(1, args.max_cases_per_source),
        seed=args.seed,
    )
    analysis = _analyze_cases(
        cases,
        args.max_numbers,
        bucket_signal_target=max(1, args.bucket_signal_target),
        calibration_ratio=max(0.1, min(0.9, float(args.calibration_ratio))),
    )
    payload = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "source": {
            "mode": args.source_mode,
            "histories_used": len(sources),
            "details": source_details,
            "calibration_cases": analysis["calibration_cases"],
            "evaluation_cases": analysis["evaluation_cases"],
        },
        "eligible_cases": analysis["eligible_cases"],
        "variants": analysis["variants"],
    }
    calibration_config = _build_calibration_config(
        analysis["calibration_buckets"],
        source_mode=args.source_mode,
        source_details=source_details,
        bucket_signal_target=max(1, args.bucket_signal_target),
    )

    args.report_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.config_out.parent.mkdir(parents=True, exist_ok=True)
    _write_markdown(args.report_out, payload)
    args.json_out.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    args.config_out.write_text(json.dumps(calibration_config, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

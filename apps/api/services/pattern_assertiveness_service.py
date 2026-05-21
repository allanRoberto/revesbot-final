"""Backtest de assertividade individual dos padrões.

Para cada `pattern_id` que aparece em `optimized_payload.contributions`,
agrega: signals, hits, hits por nível de gale, tamanho médio do set,
hit-rate, baseline aleatório esperado, lift, z-score (binomial Poisson).
"""

from __future__ import annotations

import math
import time
from collections import defaultdict
from typing import Any, Dict, List, Mapping

from api.core.db import history_coll, suggestion_snapshots_coll


DEFAULT_GALE_LEVELS = (1, 2, 3, 5)
WHEEL_SIZE = 37
CACHE_TTL_SECONDS = 600  # 10 min — o backtest fica indistinguível até chegarem snapshots novos
_report_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
_walkforward_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}


def _extract_contributions(snapshot_doc: Mapping[str, Any]) -> List[Dict[str, Any]]:
    payload = snapshot_doc.get("payload") if isinstance(snapshot_doc, Mapping) else None
    if not isinstance(payload, Mapping):
        return []
    optimized = payload.get("optimized_payload")
    if not isinstance(optimized, Mapping):
        return []
    contributions = optimized.get("contributions")
    if not isinstance(contributions, list):
        return []
    cleaned: List[Dict[str, Any]] = []
    for item in contributions:
        if not isinstance(item, Mapping):
            continue
        pid = str(item.get("pattern_id") or "").strip()
        if not pid:
            continue
        numbers = item.get("numbers") or []
        nums: List[int] = []
        for n in numbers:
            try:
                v = int(n)
            except (TypeError, ValueError):
                continue
            if 0 <= v <= 36:
                nums.append(v)
        cleaned.append({
            "pattern_id": pid,
            "pattern_name": str(item.get("pattern_name") or pid),
            "numbers": nums,
        })
    return cleaned


def _stat_bucket() -> Dict[str, Any]:
    return {
        "pattern_id": "",
        "pattern_name": "",
        "signals": 0,
        "hits": 0,
        "expected_hits": 0.0,
        "expected_variance": 0.0,
        "set_size_sum": 0,
        "set_size_min": None,
        "set_size_max": 0,
        "gale_hits": defaultdict(int),
        "gale_evaluable": defaultdict(int),
    }


def _classify(z_score: float, signals: int) -> str:
    if signals < 30:
        return "amostra_pequena"
    if z_score >= 2.5:
        return "alpha_forte"
    if z_score >= 1.5:
        return "alpha_real"
    if z_score >= 0.5:
        return "marginal"
    if z_score > -0.5:
        return "neutro"
    return "abaixo_aleatorio"


async def _load_snapshots_and_history(
    *,
    roulette_id: str,
    limit: int,
    include_all_configs: bool,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, int]]:
    snapshot_query: Dict[str, Any] = {"roulette_id": roulette_id}
    if not include_all_configs:
        from api.services.suggestion_snapshot_service import (
            build_suggestion_snapshot_config_key,
            get_or_create_global_suggestion_snapshot_config,
        )
        config_doc = await get_or_create_global_suggestion_snapshot_config()
        snapshot_query["config_key"] = build_suggestion_snapshot_config_key(config_doc)

    fetch_limit = min(limit + 20, 5500)
    snapshot_projection = {
        "anchor_history_id": 1,
        "anchor_timestamp_utc": 1,
        "payload.optimized_payload.contributions": 1,
    }
    snapshot_docs = await (
        suggestion_snapshots_coll.find(snapshot_query, snapshot_projection)
        .sort("anchor_timestamp_utc", -1)
        .limit(fetch_limit)
        .to_list(length=fetch_limit)
    )
    snapshots = [dict(doc) for doc in snapshot_docs if isinstance(doc, Mapping)]
    if not snapshots:
        raise LookupError("Nenhum snapshot de sugestão encontrado para a roleta informada.")

    history_fetch_limit = min(max(fetch_limit * 4, 500), 8000)
    history_projection = {"_id": 1, "value": 1, "timestamp": 1}
    history_docs_raw = await (
        history_coll.find({"roulette_id": roulette_id}, history_projection)
        .sort("timestamp", -1)
        .limit(history_fetch_limit)
        .to_list(length=history_fetch_limit)
    )
    history_docs = [dict(doc) for doc in history_docs_raw if isinstance(doc, Mapping)]
    history_index = {str(doc.get("_id")): idx for idx, doc in enumerate(history_docs)}
    return snapshots, history_docs, history_index


def _aggregate_stats_for_snapshots(
    snapshots: List[Dict[str, Any]],
    *,
    history_docs: List[Dict[str, Any]],
    history_index: Dict[str, int],
    gale_levels: List[int],
) -> tuple[Dict[str, Dict[str, Any]], int, int, int]:
    max_gale = max(gale_levels) if gale_levels else 1
    stats: Dict[str, Dict[str, Any]] = {}
    resolved_snapshots = 0
    unresolved_snapshots = 0
    total_evaluated_signals = 0

    for snapshot_doc in snapshots:
        anchor_history_id = str(snapshot_doc.get("anchor_history_id") or "").strip()
        if not anchor_history_id:
            unresolved_snapshots += 1
            continue
        anchor_idx = history_index.get(anchor_history_id)
        if anchor_idx is None or anchor_idx <= 0:
            unresolved_snapshots += 1
            continue

        future_numbers: List[int] = []
        for k in range(1, max_gale + 1):
            idx = anchor_idx - k
            if idx < 0:
                break
            value = history_docs[idx].get("value")
            try:
                future_numbers.append(int(value))
            except (TypeError, ValueError):
                break
        if not future_numbers:
            unresolved_snapshots += 1
            continue
        resolved_snapshots += 1
        next_number = future_numbers[0]

        contributions = _extract_contributions(snapshot_doc)
        for entry in contributions:
            pid = entry["pattern_id"]
            numbers = entry["numbers"]
            if not numbers:
                continue
            bucket = stats.get(pid)
            if bucket is None:
                bucket = _stat_bucket()
                bucket["pattern_id"] = pid
                bucket["pattern_name"] = entry["pattern_name"]
                stats[pid] = bucket
            elif not bucket["pattern_name"]:
                bucket["pattern_name"] = entry["pattern_name"]

            number_set = set(numbers)
            set_size = len(number_set)
            p = set_size / WHEEL_SIZE
            bucket["signals"] += 1
            bucket["set_size_sum"] += set_size
            bucket["set_size_max"] = max(bucket["set_size_max"], set_size)
            bucket["set_size_min"] = (
                set_size if bucket["set_size_min"] is None else min(bucket["set_size_min"], set_size)
            )
            bucket["expected_hits"] += p
            bucket["expected_variance"] += p * (1.0 - p)
            if next_number in number_set:
                bucket["hits"] += 1

            for level in gale_levels:
                available = future_numbers[:level]
                if len(available) < level:
                    continue
                bucket["gale_evaluable"][level] += 1
                if any(num in number_set for num in available):
                    bucket["gale_hits"][level] += 1

            total_evaluated_signals += 1

    return stats, resolved_snapshots, unresolved_snapshots, total_evaluated_signals


def _summarize_stats(
    stats: Dict[str, Dict[str, Any]],
    *,
    gale_levels: List[int],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for pid, bucket in stats.items():
        signals = bucket["signals"]
        if signals == 0:
            continue
        hits = bucket["hits"]
        expected = bucket["expected_hits"]
        variance = bucket["expected_variance"]
        std = math.sqrt(variance) if variance > 0 else 0.0
        z = (hits - expected) / std if std > 0 else 0.0
        avg_set = bucket["set_size_sum"] / signals
        hit_rate = hits / signals
        baseline_rate = expected / signals if signals else 0.0
        lift = (hit_rate / baseline_rate) if baseline_rate > 0 else 0.0

        gale_summary = []
        for level in gale_levels:
            evaluable = bucket["gale_evaluable"][level]
            ghits = bucket["gale_hits"][level]
            if evaluable == 0:
                continue
            p_expected = expected / signals if signals else 0
            gale_baseline = 1 - (1 - p_expected) ** level
            gale_summary.append({
                "level": level,
                "signals": evaluable,
                "hits": ghits,
                "hit_rate": round(ghits / evaluable, 4),
                "baseline_rate": round(gale_baseline, 4),
                "lift": round((ghits / evaluable) / gale_baseline, 3) if gale_baseline > 0 else 0,
            })

        rows.append({
            "pattern_id": pid,
            "pattern_name": bucket["pattern_name"],
            "signals": signals,
            "hits": hits,
            "expected_hits": round(expected, 2),
            "hit_rate": round(hit_rate, 4),
            "baseline_rate": round(baseline_rate, 4),
            "lift": round(lift, 3),
            "z_score": round(z, 3),
            "avg_set_size": round(avg_set, 2),
            "min_set_size": bucket["set_size_min"],
            "max_set_size": bucket["set_size_max"],
            "gale": gale_summary,
            "verdict": _classify(z, signals),
        })

    rows.sort(key=lambda r: r["z_score"], reverse=True)
    return rows


async def build_pattern_assertiveness_report(
    *,
    roulette_id: str,
    limit: int = 2000,
    include_all_configs: bool = False,
    gale_levels: List[int] | None = None,
) -> Dict[str, Any]:
    safe_limit = max(50, min(5000, int(limit or 2000)))
    safe_gale_levels = sorted({max(1, min(20, int(level))) for level in (gale_levels or DEFAULT_GALE_LEVELS)})

    cache_key = f"{roulette_id}|{safe_limit}|{int(include_all_configs)}|{','.join(map(str, safe_gale_levels))}"
    now = time.time()
    cached = _report_cache.get(cache_key)
    if cached and (now - cached[0]) < CACHE_TTL_SECONDS:
        cached_payload = dict(cached[1])
        cached_payload["cached"] = True
        cached_payload["cache_age_seconds"] = round(now - cached[0], 1)
        return cached_payload

    snapshots, history_docs, history_index = await _load_snapshots_and_history(
        roulette_id=roulette_id,
        limit=safe_limit,
        include_all_configs=include_all_configs,
    )
    stats, resolved, unresolved, total_evaluated = _aggregate_stats_for_snapshots(
        snapshots[:safe_limit],
        history_docs=history_docs,
        history_index=history_index,
        gale_levels=safe_gale_levels,
    )
    rows = _summarize_stats(stats, gale_levels=safe_gale_levels)

    aggregate_signals = sum(r["signals"] for r in rows)
    aggregate_hits = sum(r["hits"] for r in rows)
    aggregate_expected = sum(r["expected_hits"] for r in rows)

    report = {
        "available": True,
        "roulette_id": roulette_id,
        "requested_limit": safe_limit,
        "resolved_snapshots": resolved,
        "unresolved_snapshots": unresolved,
        "patterns_evaluated": len(rows),
        "total_evaluated_signals": total_evaluated,
        "aggregate_signals": aggregate_signals,
        "aggregate_hits": aggregate_hits,
        "aggregate_expected_hits": round(aggregate_expected, 2),
        "gale_levels": safe_gale_levels,
        "rows": rows,
        "cached": False,
    }
    _report_cache[cache_key] = (time.time(), report)
    return report


# ============================================================================
# Walk-forward — split temporal pra detectar look-ahead bias
# ============================================================================

def _classify_walkforward(
    train_z: float, test_z: float, train_n: int, test_n: int,
    *, min_signals: int = 30, sig_threshold: float = 1.0,
) -> str:
    """Categoriza a consistência entre in-sample e out-of-sample.

    - consistente_positivo: padrão tem alpha nas duas metades
    - consistente_negativo: padrão tem alpha negativo nas duas metades (drag confirmado)
    - colapsou: bom no train, ruim no test (overfit / sorte amostral)
    - virou: ruim no train, bom no test (provavelmente sorte ou regime change)
    - inconclusivo: sem n suficiente em alguma metade
    - estavel_neutro: nenhuma metade tem sinal (ruído puro)
    """
    if train_n < min_signals or test_n < min_signals:
        return "inconclusivo"
    if train_z >= sig_threshold and test_z >= sig_threshold:
        return "consistente_positivo"
    if train_z <= -sig_threshold and test_z <= -sig_threshold:
        return "consistente_negativo"
    if train_z >= sig_threshold and test_z < sig_threshold - 0.5:
        return "colapsou"
    if train_z <= -sig_threshold and test_z > -sig_threshold + 0.5:
        return "virou"
    return "estavel_neutro"


async def build_pattern_walkforward_report(
    *,
    roulette_id: str,
    limit: int = 2000,
    include_all_configs: bool = False,
    gale_levels: List[int] | None = None,
    train_ratio: float = 0.5,
) -> Dict[str, Any]:
    safe_limit = max(100, min(5000, int(limit or 2000)))
    safe_gale_levels = sorted({max(1, min(20, int(level))) for level in (gale_levels or DEFAULT_GALE_LEVELS)})
    safe_train_ratio = max(0.3, min(0.7, float(train_ratio or 0.5)))

    cache_key = f"wf|{roulette_id}|{safe_limit}|{int(include_all_configs)}|{','.join(map(str, safe_gale_levels))}|{round(safe_train_ratio,3)}"
    now = time.time()
    cached = _walkforward_cache.get(cache_key)
    if cached and (now - cached[0]) < CACHE_TTL_SECONDS:
        out = dict(cached[1])
        out["cached"] = True
        out["cache_age_seconds"] = round(now - cached[0], 1)
        return out

    snapshots, history_docs, history_index = await _load_snapshots_and_history(
        roulette_id=roulette_id,
        limit=safe_limit,
        include_all_configs=include_all_configs,
    )
    snapshots = snapshots[:safe_limit]
    # snapshots vem em ordem desc (mais recente primeiro). Para um walk-forward
    # honesto, train = metade mais ANTIGA, test = metade mais RECENTE.
    snapshots_chrono = list(reversed(snapshots))
    n_total = len(snapshots_chrono)
    split_idx = int(n_total * safe_train_ratio)
    train_snaps = snapshots_chrono[:split_idx]
    test_snaps = snapshots_chrono[split_idx:]

    train_stats, train_resolved, _, _ = _aggregate_stats_for_snapshots(
        train_snaps,
        history_docs=history_docs,
        history_index=history_index,
        gale_levels=safe_gale_levels,
    )
    test_stats, test_resolved, _, _ = _aggregate_stats_for_snapshots(
        test_snaps,
        history_docs=history_docs,
        history_index=history_index,
        gale_levels=safe_gale_levels,
    )

    train_rows = _summarize_stats(train_stats, gale_levels=safe_gale_levels)
    test_rows = _summarize_stats(test_stats, gale_levels=safe_gale_levels)

    train_map = {r["pattern_id"]: r for r in train_rows}
    test_map = {r["pattern_id"]: r for r in test_rows}
    all_pids = set(train_map) | set(test_map)

    combined: List[Dict[str, Any]] = []
    for pid in all_pids:
        tr = train_map.get(pid)
        te = test_map.get(pid)
        train_n = tr["signals"] if tr else 0
        test_n = te["signals"] if te else 0
        train_z = tr["z_score"] if tr else 0.0
        test_z = te["z_score"] if te else 0.0
        train_lift = tr["lift"] if tr else 0.0
        test_lift = te["lift"] if te else 0.0
        name = (tr["pattern_name"] if tr else (te["pattern_name"] if te else pid))
        walkforward_class = _classify_walkforward(train_z, test_z, train_n, test_n)
        # Decay simples: quanto perdeu de lift entre train e test
        lift_decay = round(test_lift - train_lift, 3) if (tr and te) else 0.0
        combined.append({
            "pattern_id": pid,
            "pattern_name": name,
            "train_signals": train_n,
            "train_hits": tr["hits"] if tr else 0,
            "train_hit_rate": tr["hit_rate"] if tr else 0.0,
            "train_baseline_rate": tr["baseline_rate"] if tr else 0.0,
            "train_lift": train_lift,
            "train_z_score": train_z,
            "train_verdict": tr["verdict"] if tr else "amostra_pequena",
            "test_signals": test_n,
            "test_hits": te["hits"] if te else 0,
            "test_hit_rate": te["hit_rate"] if te else 0.0,
            "test_baseline_rate": te["baseline_rate"] if te else 0.0,
            "test_lift": test_lift,
            "test_z_score": test_z,
            "test_verdict": te["verdict"] if te else "amostra_pequena",
            "lift_decay": lift_decay,
            "walkforward_class": walkforward_class,
        })

    # Ordem: padrões com sinal real (consistente_positivo) primeiro, depois por z_test desc
    class_order = {
        "consistente_positivo": 0,
        "colapsou": 1,
        "estavel_neutro": 2,
        "virou": 3,
        "inconclusivo": 4,
        "consistente_negativo": 5,
    }
    combined.sort(key=lambda r: (class_order.get(r["walkforward_class"], 9), -r["test_z_score"]))

    class_counts: Dict[str, int] = defaultdict(int)
    for r in combined:
        class_counts[r["walkforward_class"]] += 1

    out = {
        "available": True,
        "roulette_id": roulette_id,
        "requested_limit": safe_limit,
        "train_ratio": safe_train_ratio,
        "train_snapshots": len(train_snaps),
        "test_snapshots": len(test_snaps),
        "train_resolved": train_resolved,
        "test_resolved": test_resolved,
        "patterns_evaluated": len(combined),
        "class_counts": dict(class_counts),
        "gale_levels": safe_gale_levels,
        "rows": combined,
        "cached": False,
    }
    _walkforward_cache[cache_key] = (time.time(), out)
    return out

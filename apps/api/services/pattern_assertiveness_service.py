"""Backtest de assertividade individual dos padrões.

Para cada `pattern_id` que aparece em `optimized_payload.contributions`,
agrega: signals, hits, hits por nível de gale, tamanho médio do set,
hit-rate, baseline aleatório esperado, lift, z-score (binomial Poisson).
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Dict, List, Mapping

from api.core.db import history_coll, suggestion_snapshots_coll


DEFAULT_GALE_LEVELS = (1, 2, 3, 5)
WHEEL_SIZE = 37


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


async def build_pattern_assertiveness_report(
    *,
    roulette_id: str,
    limit: int = 2000,
    include_all_configs: bool = False,
    gale_levels: List[int] | None = None,
) -> Dict[str, Any]:
    safe_limit = max(50, min(5000, int(limit or 2000)))
    safe_gale_levels = sorted({max(1, min(20, int(level))) for level in (gale_levels or DEFAULT_GALE_LEVELS)})
    max_gale = max(safe_gale_levels) if safe_gale_levels else 1

    snapshot_query: Dict[str, Any] = {"roulette_id": roulette_id}
    if not include_all_configs:
        # Mesma estratégia do timeline: só config atual a não ser que peçam o contrário.
        from api.services.suggestion_snapshot_service import (
            build_suggestion_snapshot_config_key,
            get_or_create_global_suggestion_snapshot_config,
        )
        config_doc = await get_or_create_global_suggestion_snapshot_config()
        snapshot_query["config_key"] = build_suggestion_snapshot_config_key(config_doc)

    fetch_limit = min(safe_limit + 20, 5500)
    # Projection: só os campos que vamos usar. payload completo é gigante e
    # estoura o tempo de download/transferência sem essa redução.
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

    # Carregamos o history em ordem desc para encontrar o "próximo número" relativo
    # a cada snapshot. anchor_idx-1 é o próximo (mais novo), anchor_idx-2 o seguinte etc.
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

    stats: Dict[str, Dict[str, Any]] = {}
    resolved_snapshots = 0
    unresolved_snapshots = 0
    total_evaluated_signals = 0

    for snapshot_doc in snapshots[:safe_limit]:
        anchor_history_id = str(snapshot_doc.get("anchor_history_id") or "").strip()
        if not anchor_history_id:
            unresolved_snapshots += 1
            continue
        anchor_idx = history_index.get(anchor_history_id)
        if anchor_idx is None or anchor_idx <= 0:
            unresolved_snapshots += 1
            continue

        # Próximos N giros (em ordem cronológica crescente: 1° = next, 2° = next+1...)
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

            set_size = len(set(numbers))
            p = set_size / WHEEL_SIZE
            bucket["signals"] += 1
            bucket["set_size_sum"] += set_size
            bucket["set_size_max"] = max(bucket["set_size_max"], set_size)
            bucket["set_size_min"] = (
                set_size if bucket["set_size_min"] is None else min(bucket["set_size_min"], set_size)
            )
            bucket["expected_hits"] += p
            bucket["expected_variance"] += p * (1.0 - p)
            number_set = set(numbers)
            if next_number in number_set:
                bucket["hits"] += 1

            # Gale-N: bate se o número saiu em qualquer uma das primeiras N tentativas.
            # gale_evaluable é menor quando faltam giros futuros suficientes.
            for level in safe_gale_levels:
                available = future_numbers[:level]
                if len(available) < level:
                    continue
                bucket["gale_evaluable"][level] += 1
                if any(num in number_set for num in available):
                    bucket["gale_hits"][level] += 1

            total_evaluated_signals += 1

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
        for level in safe_gale_levels:
            evaluable = bucket["gale_evaluable"][level]
            ghits = bucket["gale_hits"][level]
            if evaluable == 0:
                continue
            # Baseline para gale: 1 - (1 - p)^level
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

    aggregate_signals = sum(r["signals"] for r in rows)
    aggregate_hits = sum(r["hits"] for r in rows)
    aggregate_expected = sum(r["expected_hits"] for r in rows)

    return {
        "available": True,
        "roulette_id": roulette_id,
        "requested_limit": safe_limit,
        "resolved_snapshots": resolved_snapshots,
        "unresolved_snapshots": unresolved_snapshots,
        "patterns_evaluated": len(rows),
        "total_evaluated_signals": total_evaluated_signals,
        "aggregate_signals": aggregate_signals,
        "aggregate_hits": aggregate_hits,
        "aggregate_expected_hits": round(aggregate_expected, 2),
        "gale_levels": safe_gale_levels,
        "rows": rows,
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

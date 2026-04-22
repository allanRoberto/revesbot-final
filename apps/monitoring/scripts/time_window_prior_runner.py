from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pprint import pprint
from time import sleep
from typing import Any, Dict, List

import requests

from src.config import settings
from src.mongo import mongo_db
from src.time_window_prior import (
    BR_TZ,
    build_daily_window_bounds,
    build_reference_time,
    compute_time_window_priors,
    rerank_with_time_window_prior,
)

LOCAL_DEFAULT_API_BASE_URL = "http://localhost:8081"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Consulta prior temporal por horário e reranqueia a simple-suggestion com base no histórico recente."
    )
    parser.add_argument("--roulette-id", default="pragmatic-auto-roulette")
    parser.add_argument("--time", default=None, help="Horário de referência em HH:MM. Se omitido, usa o minuto atual.")
    parser.add_argument("--lookback-days", type=int, default=5)
    parser.add_argument("--minute-span", type=int, default=2)
    parser.add_argument("--region-span", type=int, default=2)
    parser.add_argument("--history-window", type=int, default=500)
    parser.add_argument("--max-numbers", type=int, default=37)
    parser.add_argument("--api-base-url", default=LOCAL_DEFAULT_API_BASE_URL)
    parser.add_argument("--simple-path", default=settings.suggestion_monitor_simple_path)
    parser.add_argument("--watch", action="store_true", help="Executa continuamente, recalculando a cada novo minuto.")
    parser.add_argument("--json", action="store_true", help="Imprime resultado consolidado em JSON.")
    return parser.parse_args()


def load_latest_history(roulette_id: str, history_window: int) -> List[Dict[str, Any]]:
    coll = mongo_db["history"]
    cursor = coll.find(
        {"$or": [{"roulette_id": roulette_id}, {"slug": roulette_id}]},
        sort=[("timestamp", -1)],
        limit=max(10, int(history_window)),
    )
    return [dict(item) for item in cursor]


def load_window_docs_by_day(
    *,
    roulette_id: str,
    reference_br,
    lookback_days: int,
    minute_span: int,
) -> Dict[str, List[Dict[str, Any]]]:
    coll = mongo_db["history"]
    docs_by_day: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for days_ago in range(1, max(1, int(lookback_days)) + 1):
        day_reference = reference_br - timedelta(days=days_ago)
        start_br, end_br = build_daily_window_bounds(day_reference, minute_span=minute_span)
        start_utc = start_br.astimezone(timezone.utc)
        end_utc = end_br.astimezone(timezone.utc)
        day_docs = list(
            coll.find(
                {
                    "$or": [{"roulette_id": roulette_id}, {"slug": roulette_id}],
                    "timestamp": {"$gte": start_utc, "$lt": end_utc},
                },
                sort=[("timestamp", 1)],
            )
        )
        docs_by_day[day_reference.strftime("%Y-%m-%d")] = [dict(item) for item in day_docs]
    return dict(docs_by_day)


def fetch_simple_suggestion(
    *,
    base_url: str,
    simple_path: str,
    history_values: List[int],
    focus_number: int,
    max_numbers: int,
) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}{simple_path}"
    payload = {
        "history": history_values,
        "focus_number": int(focus_number),
        "from_index": 0,
        "max_numbers": int(max_numbers),
        "optimized_max_numbers": int(max_numbers),
        "base_weight": float(settings.suggestion_monitor_base_weight),
        "optimized_weight": float(settings.suggestion_monitor_optimized_weight),
        "runtime_overrides": dict(settings.suggestion_monitor_runtime_overrides),
        "siege_window": int(settings.suggestion_monitor_siege_window),
        "siege_min_occurrences": int(settings.suggestion_monitor_siege_min_occurrences),
        "siege_min_streak": int(settings.suggestion_monitor_siege_min_streak),
        "siege_veto_relief": float(settings.suggestion_monitor_siege_veto_relief),
        "block_bets_enabled": bool(settings.suggestion_monitor_block_bets_enabled),
        "inversion_enabled": bool(settings.suggestion_monitor_inversion_enabled),
        "inversion_context_window": int(settings.suggestion_monitor_inversion_context_window),
        "inversion_penalty_factor": float(settings.suggestion_monitor_inversion_penalty_factor),
        "weight_profile_id": settings.suggestion_monitor_weight_profile_id,
        "protected_mode_enabled": bool(settings.suggestion_monitor_protected_mode_enabled),
        "protected_suggestion_size": int(settings.suggestion_monitor_protected_suggestion_size),
        "protected_swap_enabled": bool(settings.suggestion_monitor_protected_swap_enabled),
        "cold_count": int(settings.suggestion_monitor_cold_count),
    }
    response = requests.post(url, json=payload, timeout=max(5, int(settings.suggestion_monitor_api_timeout_seconds)))
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        body_preview = response.text[:300]
        raise RuntimeError(f"Falha ao consultar simple-suggestion em {url}: {response.status_code} {body_preview}") from exc
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"Resposta inesperada da simple-suggestion: {type(data)!r}")
    return data


def build_result(args: argparse.Namespace, reference_br) -> Dict[str, Any]:
    latest_docs = load_latest_history(args.roulette_id, args.history_window)
    if not latest_docs:
        raise RuntimeError("Nenhum histórico encontrado para a roleta informada.")

    history_values = [int(doc.get("value")) for doc in latest_docs if doc.get("value") is not None]
    focus_number = int(history_values[0])
    docs_by_day = load_window_docs_by_day(
        roulette_id=args.roulette_id,
        reference_br=reference_br,
        lookback_days=args.lookback_days,
        minute_span=args.minute_span,
    )
    prior_summary = compute_time_window_priors(
        docs_by_day,
        lookback_days=args.lookback_days,
        region_span=args.region_span,
    )
    simple_payload = fetch_simple_suggestion(
        base_url=args.api_base_url,
        simple_path=args.simple_path,
        history_values=history_values,
        focus_number=focus_number,
        max_numbers=args.max_numbers,
    )
    reranked = rerank_with_time_window_prior(
        simple_payload,
        exact_prior=prior_summary["exact_prior"],
        region_prior=prior_summary["region_prior"],
    )

    return {
        "roulette_id": args.roulette_id,
        "reference_time_br": reference_br.strftime("%Y-%m-%d %H:%M:%S"),
        "window_start_br": build_daily_window_bounds(reference_br, minute_span=args.minute_span)[0].strftime("%H:%M:%S"),
        "window_end_br_exclusive": build_daily_window_bounds(reference_br, minute_span=args.minute_span)[1].strftime("%H:%M:%S"),
        "lookback_days": int(args.lookback_days),
        "minute_span": int(args.minute_span),
        "region_span": int(args.region_span),
        "focus_number": int(focus_number),
        "history_sample_size": len(history_values),
        "historical_summary": {
            "days_with_data": int(prior_summary["days_with_data"]),
            "total_spins": int(prior_summary["total_spins"]),
            "avg_spins_per_day": float(prior_summary["avg_spins_per_day"]),
            "top_exact": prior_summary["top_exact"],
            "top_region": prior_summary["top_region"],
        },
        "simple_suggestion": list(simple_payload.get("ordered_suggestion") or simple_payload.get("suggestion") or []),
        "temporal_reranked_suggestion": reranked["ordered_suggestion"],
        "ranking_components": reranked["components"],
    }


def print_result(result: Dict[str, Any], *, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    print(f"Roleta: {result['roulette_id']}")
    print(f"Horário de referência (BR): {result['reference_time_br']}")
    print(
        f"Janela temporal: {result['window_start_br']} até {result['window_end_br_exclusive']} (exclusivo) | "
        f"lookback={result['lookback_days']} dias | span_minutos=±{result['minute_span']}"
    )
    print(f"Focus number atual: {result['focus_number']}")
    print(
        f"Amostra histórica: {result['historical_summary']['days_with_data']} dias com dados | "
        f"{result['historical_summary']['total_spins']} spins | "
        f"média {result['historical_summary']['avg_spins_per_day']:.2f}/dia"
    )
    print("Top frequência exata:")
    for item in result["historical_summary"]["top_exact"][:10]:
        print(f"  {item['number']:>2} -> {item['score']:.3f}")
    print("Top frequência regional:")
    for item in result["historical_summary"]["top_region"][:10]:
        print(f"  {item['number']:>2} -> {item['score']:.3f}")
    print("Sugestão atual:")
    print(" ", result["simple_suggestion"])
    print("Sugestão reranqueada pelo prior temporal:")
    print(" ", result["temporal_reranked_suggestion"])
    print("Top 12 componentes do reranqueamento:")
    pprint(result["ranking_components"][:12])


def wait_until_next_minute() -> None:
    now_br = datetime.now(BR_TZ)
    next_minute_br = now_br.replace(second=0, microsecond=0) + timedelta(minutes=1)
    seconds = (next_minute_br - now_br).total_seconds() + 0.25
    sleep(max(1.0, seconds))


def main() -> None:
    args = parse_args()
    while True:
        reference_br = build_reference_time(args.time if not args.watch else None)
        result = build_result(args, reference_br)
        print_result(result, as_json=args.json)
        if not args.watch:
            return
        if not args.json:
            print("-" * 80)
        wait_until_next_minute()

if __name__ == "__main__":
    main()

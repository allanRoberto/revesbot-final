from __future__ import annotations

from datetime import datetime, timedelta, date
from typing import Any, Dict, List, Optional, Set, Tuple

import pytz
from fastapi import APIRouter, HTTPException

from api.core.db import history_coll


router = APIRouter()


@router.get("/api/analise/previsao-sequencia/{roulette_id}")
async def get_sequence_prediction(
    roulette_id: str,
    time: str,                 # HH:MM
    interval: int = 3,         # minutos (1..30)
    days_back: int = 30,       # dias de histórico
    min_len: int = 3,          # tamanho mínimo da sequência
    max_len: int = 7,          # tamanho máximo da sequência
    seed: Optional[int] = None # opcional: filtrar sequências que comecem com este número
):
    """
    Analisa, para um horário ±interval, as sequências de números que se formam em cada dia
    e agrega a recorrência dessas sequências ao longo de 'days_back'.
    Também retorna estatísticas por número no mesmo intervalo (p/ tooltips).
    """
    try:
        hour, minute = map(int, time.split(":"))

        start_minute = minute - interval
        end_minute = minute + interval
        start_hour = hour
        end_hour = hour

        if start_minute < 0:
            start_hour = (hour - 1) % 24
            start_minute = 60 + start_minute
        if end_minute >= 60:
            end_hour = (hour + 1) % 24
            end_minute = end_minute % 60

        start_date = datetime.now() - timedelta(days=days_back)
        filter_query = {
            "roulette_id": roulette_id,
            "timestamp": {"$gte": start_date},
        }
        cursor = history_coll.find(filter_query)
        results = await cursor.to_list(length=None)

        tz_br = pytz.timezone("America/Sao_Paulo")

        def in_window(h: int, m: int) -> bool:
            if start_hour == end_hour:
                return (h == start_hour) and (start_minute <= m < end_minute)
            return ((h == start_hour and m >= start_minute) or
                    (h == end_hour and m < end_minute))

        by_date: Dict[str, List[Tuple[datetime, int]]] = {}
        number_interval_stats: Dict[int, Dict[str, Any]] = {}
        total_in_interval = 0
        days_with_data: Set[date] = set()

        for doc in results:
            ts = doc["timestamp"]
            if ts.tzinfo is None:
                ts = pytz.utc.localize(ts)
            br_ts = ts.astimezone(tz_br)

            if in_window(br_ts.hour, br_ts.minute):
                n = int(doc["value"])
                dkey = br_ts.date().isoformat()

                by_date.setdefault(dkey, []).append((br_ts, n))

                if n not in number_interval_stats:
                    number_interval_stats[n] = {"total": 0, "days": 0, "by_date": {}}
                number_interval_stats[n]["total"] += 1
                number_interval_stats[n]["by_date"][dkey] = (
                    number_interval_stats[n]["by_date"].get(dkey, 0) + 1
                )

                total_in_interval += 1
                days_with_data.add(br_ts.date())

        for n, stats in number_interval_stats.items():
            stats["days"] = len(stats["by_date"])

        daily_sequences = []
        for dkey, items in by_date.items():
            items.sort(key=lambda x: x[0])
            seq_numbers = [n for _, n in items]
            seq_times = [t.strftime("%H:%M:%S") for t, _ in items]
            daily_sequences.append({
                "date": dkey,
                "numbers": seq_numbers,
                "times": seq_times,
            })
        daily_sequences.sort(key=lambda d: d["date"])

        sequences_index: Dict[str, List[Dict[str, Any]]] = {
            str(k): [] for k in range(min_len, max_len + 1)
        }
        agg: Dict[Tuple[int, Tuple[int, ...]], Dict[str, Any]] = {}

        for d in daily_sequences:
            seq = d["numbers"]
            times = d["times"]
            L = len(seq)
            if L == 0:
                continue

            for k in range(min_len, max_len + 1):
                if L < k:
                    continue
                for i in range(0, L - k + 1):
                    sub_seq = seq[i:i + k]
                    if seed is not None and sub_seq[0] != seed:
                        continue
                    key = (k, tuple(sub_seq))
                    if key not in agg:
                        agg[key] = {"total": 0, "days": set(), "by_date": {}}
                    agg[key]["total"] += 1
                    agg[key]["days"].add(d["date"])

                    t0 = times[i] if i < len(times) else None
                    by_date_map = agg[key]["by_date"]
                    by_date_map.setdefault(d["date"], [])
                    if t0:
                        by_date_map[d["date"]].append(t0)

        TOP_PER_SIZE = 30
        buckets: Dict[int, List[Tuple[Tuple[int, ...], Dict[str, Any]]]] = {}
        for (k, seq_tuple), data in agg.items():
            buckets.setdefault(k, []).append((seq_tuple, data))

        for k, items in buckets.items():
            items.sort(key=lambda x: x[1]["total"], reverse=True)
            top_items = items[:TOP_PER_SIZE]
            sequences_index[str(k)] = [
                {
                    "sequence": list(seq_tuple),
                    "total": data["total"],
                    "total_days": len(data["days"]),
                    "by_date": data["by_date"],
                }
                for seq_tuple, data in top_items
            ]

        return {
            "time_base": f"{hour:02d}:{minute:02d}",
            "interval_minutes": interval,
            "interval_start": f"{start_hour:02d}:{start_minute:02d}",
            "interval_end": f"{end_hour:02d}:{end_minute:02d}",
            "days_analyzed": days_back,
            "total_occurrences_in_interval": total_in_interval,
            "days_with_occurrences": len(days_with_data),
            "daily_sequences": daily_sequences,
            "number_interval_stats": number_interval_stats,
            "sequences_index": sequences_index,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

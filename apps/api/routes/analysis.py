from __future__ import annotations

import math
from datetime import datetime, timedelta, date
from typing import Any, Dict, List, Optional, Tuple

import pytz
from fastapi import APIRouter, HTTPException

from api.core.db import history_coll
from api.services.roulette_analysis import (
    EURO_WHEEL_ORDER,
    IDX2NUM,
    WHEEL_SIZE,
    add_vectors,
    cosine_similarity,
    count_vector_for_day,
    indices_to_numbers,
    overlap_size,
    parse_time_window,
    sector_indices,
    slide_window_wrap,
)


router = APIRouter()


@router.get("/api/analise/region-hotspot/{roulette_id}")
async def get_region_hotspot(
    roulette_id: str,
    time: str,                 # HH:MM
    interval: int = 3,         # minutos (1..30)
    days_back: int = 30,       # dias de histórico
    neighbor_span: int = 8,    # central + 8 vizinhos de cada lado (17 números)
    min_today_spins: int = 6,  # mínimo de ocorrências hoje no intervalo para validar
    min_similarity: float = 0.75,  # similaridade mínima média vs dias passados
    min_support_days: int = 3       # mínimo de dias com similaridade >= min_similarity
):
    """
    Identifica regiões quentes (setores) por horário e mede similaridade com dias anteriores.
    Sugere entrada no número central + 8 vizinhos quando:
      - há setor quente hoje com suporte de ocorrências suficientes,
      - há convergência com o setor histórico agregado nesse mesmo horário,
      - e existem ao menos 'min_support_days' dias com similaridade >= 'min_similarity'.
    """
    try:
        base_hour, base_minute = map(int, time.split(":"))
        start_hour, start_minute, end_hour, end_minute = parse_time_window(time, interval)

        start_date = datetime.now() - timedelta(days=days_back)
        filter_query = {
            "roulette_id": roulette_id,
            "timestamp": {"$gte": start_date},
        }
        cursor = history_coll.find(filter_query)
        rows = await cursor.to_list(length=None)

        tz_br = pytz.timezone("America/Sao_Paulo")

        def in_window(h: int, m: int) -> bool:
            if start_hour == end_hour:
                return (h == start_hour) and (start_minute <= m < end_minute)
            return ((h == start_hour and m >= start_minute) or
                    (h == end_hour and m < end_minute))

        by_date_raw: Dict[str, List[Tuple[datetime, int]]] = {}
        for doc in rows:
            ts = doc["timestamp"]
            if ts.tzinfo is None:
                ts = pytz.utc.localize(ts)
            br_ts = ts.astimezone(tz_br)
            if in_window(br_ts.hour, br_ts.minute):
                n = int(doc["value"])
                dkey = br_ts.date().isoformat()
                by_date_raw.setdefault(dkey, []).append((br_ts, n))

        if not by_date_raw:
            return {
                "time_base": f"{base_hour:02d}:{base_minute:02d}",
                "interval_minutes": interval,
                "interval_start": f"{start_hour:02d}:{start_minute:02d}",
                "interval_end": f"{end_hour:02d}:{end_minute:02d}",
                "days_analyzed": days_back,
                "message": "Sem dados para o intervalo informado.",
                "recommendation": {"enter": False},
            }

        days_sorted = sorted(by_date_raw.keys())
        per_day_numbers: Dict[str, List[int]] = {}
        for d in days_sorted:
            items = sorted(by_date_raw[d], key=lambda x: x[0])
            per_day_numbers[d] = [n for _, n in items]

        today_key = days_sorted[-1]
        today_numbers = per_day_numbers[today_key]
        today_count = len(today_numbers)

        per_day_vec: Dict[str, List[int]] = {}
        hist_vec_agg: List[int] = [0] * WHEEL_SIZE
        support_days = 0

        for d, nums in per_day_numbers.items():
            vec = count_vector_for_day(nums)
            per_day_vec[d] = vec
            if d != today_key:
                if sum(vec) > 0:
                    add_vectors(hist_vec_agg, vec)
                    support_days += 1

        has_hist = support_days > 0

        window_size = (2 * neighbor_span) + 1
        today_vec = per_day_vec[today_key]
        today_center_idx, today_sector_sum = slide_window_wrap(today_vec, window_size)
        today_sector_idxs = sector_indices(today_center_idx, neighbor_span)
        today_sector_numbers = indices_to_numbers(today_sector_idxs)

        if has_hist:
            hist_center_idx, hist_sector_sum = slide_window_wrap(hist_vec_agg, window_size)
            hist_sector_idxs = sector_indices(hist_center_idx, neighbor_span)
            hist_sector_numbers = indices_to_numbers(hist_sector_idxs)
        else:
            hist_center_idx = None
            hist_sector_sum = 0
            hist_sector_idxs = []
            hist_sector_numbers = []

        similarities: List[Dict[str, Any]] = []
        sim_support = 0
        sim_sum = 0.0
        for d in days_sorted[:-1]:
            vec_d = per_day_vec[d]
            sim = cosine_similarity([float(x) for x in today_vec], [float(y) for y in vec_d])
            d_center, _ = slide_window_wrap(vec_d, window_size) if sum(vec_d) > 0 else (None, 0)
            if d_center is not None:
                d_sector = set(sector_indices(d_center, neighbor_span))
                top_overlap = overlap_size(set(today_sector_idxs), d_sector)
            else:
                top_overlap = 0

            similarities.append({
                "date": d,
                "similarity": round(sim, 4),
                "top_overlap": int(top_overlap),
                "day_spins": int(sum(vec_d)),
                "day_center": (IDX2NUM[d_center] if d_center is not None else None),
            })
            if sim >= min_similarity:
                sim_support += 1
                sim_sum += sim

        avg_similarity = (sim_sum / sim_support) if sim_support > 0 else 0.0

        enter = False
        rationale: Dict[str, Any] = {
            "today_spins": today_count,
            "today_sector_sum": int(today_sector_sum),
            "sim_support_days": sim_support,
            "avg_similarity_above_threshold": round(avg_similarity, 4),
            "hist_sector_alignment": None,
        }

        if today_count >= min_today_spins and sim_support >= min_support_days and has_hist:
            inter = overlap_size(set(today_sector_idxs), set(hist_sector_idxs))
            rationale["hist_sector_alignment"] = inter
            if inter >= math.ceil(window_size * 0.5):
                enter = True

        recommendation = {
            "enter": enter,
            "center": IDX2NUM[today_center_idx] if enter else None,
            "neighbors": today_sector_numbers if enter else [],
            "thresholds": {
                "min_today_spins": min_today_spins,
                "min_similarity": min_similarity,
                "min_support_days": min_support_days,
            },
            "rationale": rationale,
        }

        return {
            "time_base": f"{base_hour:02d}:{base_minute:02d}",
            "interval_minutes": interval,
            "interval_start": f"{start_hour:02d}:{start_minute:02d}",
            "interval_end": f"{end_hour:02d}:{end_minute:02d}",
            "days_analyzed": days_back,

            "today": {
                "date": today_key,
                "spins": today_count,
                "hot_center": IDX2NUM[today_center_idx],
                "hot_numbers": today_sector_numbers,
                "sector_sum": int(today_sector_sum),
                "distribution_by_wheel_index": today_vec,
            },

            "historical": {
                "days": support_days,
                "hot_center": (IDX2NUM[hist_center_idx] if has_hist else None),
                "hot_numbers": hist_sector_numbers,
                "sector_sum": int(hist_sector_sum) if has_hist else 0,
                "distribution_by_wheel_index": hist_vec_agg,
            },

            "similarities": sorted(similarities, key=lambda x: x["date"], reverse=True),
            "recommendation": recommendation,
            "wheel_order": EURO_WHEEL_ORDER,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

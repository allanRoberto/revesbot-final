from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
import math
from statistics import mean
from typing import Any, Dict, Iterable, List, Sequence

import pytz

from api.core.db import history_coll
from api.services.roulette_analysis import (
    IDX2NUM,
    NUM2IDX,
    WHEEL_SIZE,
    get_br_timezone,
    indices_to_numbers,
    sector_indices,
    slide_window_wrap,
)


DEFAULT_MAX_RECORDS = 5000
DEFAULT_DAYS_BACK = 30
DEFAULT_STATE_WINDOW = 6
DEFAULT_FUTURE_HORIZON = 5
DEFAULT_VALIDATION_RATIO = 0.25
DEFAULT_TOP_K = 12
DEFAULT_EPISODE_LIMIT = 80
DEFAULT_SIMILARITY_THRESHOLD = 0.54
DEFAULT_HORIZON_SET = (1, 3, 5, 8)
HOTSPOT_WINDOW_SIZE = 7
EPSILON = 1e-9

RED_NUMBERS = {
    1, 3, 5, 7, 9, 12, 14, 16, 18, 19,
    21, 23, 25, 27, 30, 32, 34, 36,
}


def _coerce_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise TypeError(f"Timestamp inválido para decoder_lab: {value!r}")


def _normalize_rows(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for row in rows:
        if "value" not in row or "timestamp" not in row:
            continue
        normalized.append(
            {
                "value": int(row["value"]),
                "timestamp": _coerce_timestamp(row["timestamp"]),
            }
        )
    normalized.sort(key=lambda item: item["timestamp"])
    return normalized


def _number_color(number: int) -> str:
    if number == 0:
        return "green"
    return "red" if number in RED_NUMBERS else "black"


def _number_parity(number: int) -> str:
    if number == 0:
        return "zero"
    return "even" if number % 2 == 0 else "odd"


def _number_high_low(number: int) -> str:
    if number == 0:
        return "zero"
    return "low" if number <= 18 else "high"


def _number_dozen(number: int) -> int:
    if number == 0:
        return 0
    return ((number - 1) // 12) + 1


def _number_column(number: int) -> int:
    if number == 0:
        return 0
    remainder = number % 3
    return 3 if remainder == 0 else remainder


def _signed_circular_delta(from_idx: int, to_idx: int) -> int:
    delta = (to_idx - from_idx) % WHEEL_SIZE
    if delta > (WHEEL_SIZE // 2):
        delta -= WHEEL_SIZE
    return delta


def _circular_distance(a_idx: int, b_idx: int) -> int:
    raw = abs(a_idx - b_idx)
    return min(raw, WHEEL_SIZE - raw)


def _circular_span(indices: Sequence[int]) -> int:
    if len(indices) <= 1:
        return 0
    ordered = sorted(set(indices))
    if len(ordered) <= 1:
        return 0
    gaps = []
    for idx in range(len(ordered) - 1):
        gaps.append(ordered[idx + 1] - ordered[idx])
    gaps.append((ordered[0] + WHEEL_SIZE) - ordered[-1])
    largest_gap = max(gaps)
    return WHEEL_SIZE - largest_gap


def _normalize_metric(raw_map: Dict[int, float], *, cap: float | None = None) -> Dict[int, float]:
    if not raw_map:
        return {}

    prepared: Dict[int, float] = {}
    for number, value in raw_map.items():
        prepared[number] = min(value, cap) if cap is not None else float(value)

    min_value = min(prepared.values())
    max_value = max(prepared.values())
    if max_value <= min_value + EPSILON:
        return {number: (1.0 if max_value > 0.0 else 0.0) for number in prepared}

    spread = max_value - min_value
    return {number: (value - min_value) / spread for number, value in prepared.items()}


def _counter_similarity(counter_a: Counter[Any], counter_b: Counter[Any], total: int) -> float:
    if total <= 0:
        return 0.0
    keys = set(counter_a) | set(counter_b)
    return sum(min(counter_a.get(key, 0), counter_b.get(key, 0)) for key in keys) / total


def _hour_similarity(hour_a: int | None, hour_b: int | None) -> float:
    if hour_a is None or hour_b is None:
        return 0.5
    distance = abs(hour_a - hour_b)
    distance = min(distance, 24 - distance)
    return max(0.0, 1.0 - (distance / 12.0))


def _gap_similarity(gap_a: float | None, gap_b: float | None) -> float:
    if gap_a is None or gap_b is None:
        return 0.5
    return max(0.0, 1.0 - min(abs(gap_a - gap_b), 120.0) / 120.0)


def _build_hotspot(weight_map: Dict[int, float]) -> tuple[Dict[str, Any], Dict[int, float]]:
    vec = [0.0] * WHEEL_SIZE
    for number, weight in weight_map.items():
        idx = NUM2IDX.get(number)
        if idx is not None:
            vec[idx] += float(weight)

    if not any(vec):
        return {
            "window_size": HOTSPOT_WINDOW_SIZE,
            "center": None,
            "center_index": None,
            "numbers": [],
            "sector_sum": 0.0,
        }, {number: 0.0 for number in range(37)}

    center_idx, sector_sum = slide_window_wrap(vec, HOTSPOT_WINDOW_SIZE)
    half_window = HOTSPOT_WINDOW_SIZE // 2
    hotspot_indices = sector_indices(center_idx, half_window)
    hotspot_numbers = indices_to_numbers(hotspot_indices)

    cluster_raw: Dict[int, float] = {}
    for number in range(37):
        distance = _circular_distance(NUM2IDX[number], center_idx)
        cluster_raw[number] = 1.0 / (1.0 + distance)

    return {
        "window_size": HOTSPOT_WINDOW_SIZE,
        "center": IDX2NUM[center_idx],
        "center_index": center_idx,
        "numbers": hotspot_numbers,
        "sector_sum": round(float(sector_sum), 4),
    }, _normalize_metric(cluster_raw)


def _color_alternation(colors: Sequence[str]) -> float:
    if len(colors) <= 1:
        return 0.0
    comparisons = 0
    alternations = 0
    for idx in range(len(colors) - 1):
        if "zero" in (colors[idx], colors[idx + 1], "green"):
            comparisons += 1
            alternations += int(colors[idx] != colors[idx + 1])
        else:
            comparisons += 1
            alternations += int(colors[idx] != colors[idx + 1])
    return alternations / max(1, comparisons)


def _direction_change_rate(directions: Sequence[int]) -> float:
    normalized = [0 if direction == 0 else (1 if direction > 0 else -1) for direction in directions]
    meaningful = [direction for direction in normalized if direction != 0]
    if len(meaningful) <= 1:
        return 0.0
    changes = 0
    for idx in range(len(meaningful) - 1):
        if meaningful[idx] != meaningful[idx + 1]:
            changes += 1
    return changes / max(1, len(meaningful) - 1)


def _classify_regimes(state: Dict[str, Any]) -> List[str]:
    labels: List[str] = []

    if state["sector_span"] <= 10:
        labels.append("clustered_sector")
    if state["mean_abs_delta"] <= 4.5:
        labels.append("short_hops")
    if state["mean_abs_delta"] >= 10.0:
        labels.append("wide_jumps")
    if state["direction_change_rate"] >= 0.66:
        labels.append("alternating_direction")
    if state["duplicates"] > 0:
        labels.append("repeat_pressure")
    if state["same_terminal_strength"] >= 2:
        labels.append("terminal_bias")
    if state["color_alternation_rate"] >= 0.75:
        labels.append("color_rotation")
    if state["zero_count"] > 0:
        labels.append("zero_anchor")
    if state["avg_gap_sec"] is not None and state["avg_gap_sec"] < 45.0:
        labels.append("fast_cycle")
    if not labels:
        labels.append("balanced_flow")
    return labels


def _describe_state(
    numbers: Sequence[int],
    *,
    timestamps: Sequence[datetime] | None = None,
    source: str,
) -> Dict[str, Any]:
    values = [int(number) for number in numbers]
    indices = [NUM2IDX[number] for number in values]
    deltas = [
        _signed_circular_delta(indices[idx], indices[idx + 1])
        for idx in range(len(indices) - 1)
    ]
    abs_deltas = [abs(delta) for delta in deltas]
    directions = [0 if delta == 0 else (1 if delta > 0 else -1) for delta in deltas]
    terminals = [number % 10 for number in values]
    colors = [_number_color(number) for number in values]
    parity = [_number_parity(number) for number in values]
    high_low = [_number_high_low(number) for number in values]
    dozens = [_number_dozen(number) for number in values]
    columns = [_number_column(number) for number in values]

    timestamp_list = list(timestamps or [])
    hour = None
    avg_gap_sec = None
    if timestamp_list:
        tz_br = get_br_timezone()
        end_ts = timestamp_list[-1]
        if end_ts.tzinfo is None:
            end_ts = pytz.utc.localize(end_ts)
        hour = end_ts.astimezone(tz_br).hour
        if len(timestamp_list) > 1:
            gaps = [
                (timestamp_list[idx + 1] - timestamp_list[idx]).total_seconds()
                for idx in range(len(timestamp_list) - 1)
            ]
            avg_gap_sec = mean(gaps)

    hotspot, _ = _build_hotspot(Counter(values))

    state = {
        "source": source,
        "numbers": values,
        "indices": indices,
        "deltas": deltas,
        "abs_deltas": abs_deltas,
        "mean_abs_delta": round(mean(abs_deltas) if abs_deltas else 0.0, 4),
        "direction_change_rate": round(_direction_change_rate(directions), 4),
        "sector_span": int(_circular_span(indices)),
        "duplicates": len(values) - len(set(values)),
        "same_terminal_strength": max(Counter(terminals).values()) if terminals else 0,
        "zero_count": values.count(0),
        "color_alternation_rate": round(_color_alternation(colors), 4),
        "terminal_counts": dict(Counter(terminals)),
        "color_counts": dict(Counter(colors)),
        "parity_counts": dict(Counter(parity)),
        "high_low_counts": dict(Counter(high_low)),
        "dozen_counts": dict(Counter(dozens)),
        "column_counts": dict(Counter(columns)),
        "hour": hour,
        "avg_gap_sec": round(avg_gap_sec, 2) if avg_gap_sec is not None else None,
        "hotspot": hotspot,
    }
    state["active_regimes"] = _classify_regimes(state)
    return state


def _build_episode(
    rows: Sequence[Dict[str, Any]],
    *,
    end_idx: int,
    state_window: int,
    max_horizon: int,
) -> Dict[str, Any]:
    state_rows = rows[end_idx - state_window + 1 : end_idx + 1]
    future_rows = rows[end_idx + 1 : end_idx + 1 + max_horizon]
    state = _describe_state(
        [row["value"] for row in state_rows],
        timestamps=[row["timestamp"] for row in state_rows],
        source="history",
    )
    return {
        "end_index": end_idx,
        "end_timestamp": state_rows[-1]["timestamp"].isoformat(),
        "state": state,
        "future": [row["value"] for row in future_rows],
        "future_timestamps": [row["timestamp"].isoformat() for row in future_rows],
    }


def _build_episode_bank(
    rows: Sequence[Dict[str, Any]],
    *,
    state_window: int,
    max_horizon: int,
) -> List[Dict[str, Any]]:
    episodes: List[Dict[str, Any]] = []
    if len(rows) < state_window + max_horizon:
        return episodes
    for end_idx in range(state_window - 1, len(rows) - max_horizon):
        episodes.append(
            _build_episode(
                rows,
                end_idx=end_idx,
                state_window=state_window,
                max_horizon=max_horizon,
            )
        )
    return episodes


def _build_current_state(
    rows: Sequence[Dict[str, Any]],
    *,
    state_numbers: Sequence[int] | None,
    state_window: int,
) -> Dict[str, Any]:
    manual_numbers = [int(number) for number in (state_numbers or []) if str(number).strip() != ""]
    if manual_numbers:
        return _describe_state(manual_numbers, source="manual")
    if len(rows) < state_window:
        raise ValueError("Histórico insuficiente para montar o estado atual.")
    state_rows = rows[-state_window:]
    return _describe_state(
        [row["value"] for row in state_rows],
        timestamps=[row["timestamp"] for row in state_rows],
        source="latest_history",
    )


def _split_episode_bank(
    episodes: Sequence[Dict[str, Any]],
    *,
    validation_ratio: float,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    total = len(episodes)
    if total < 12:
        return list(episodes), []
    holdout_size = max(1, int(round(total * max(0.0, min(validation_ratio, 0.45)))))
    holdout_size = min(holdout_size, total - 6)
    return list(episodes[:-holdout_size]), list(episodes[-holdout_size:])


def _episode_similarity(current_state: Dict[str, Any], episode: Dict[str, Any]) -> Dict[str, Any]:
    candidate = episode["state"]
    current_numbers = current_state["numbers"]
    candidate_numbers = candidate["numbers"]
    current_indices = current_state["indices"]
    candidate_indices = candidate["indices"]
    current_deltas = current_state["deltas"]
    candidate_deltas = candidate["deltas"]
    window_size = max(1, len(current_numbers))

    number_overlap = len(set(current_numbers).intersection(candidate_numbers)) / window_size
    position_match = sum(
        1
        for left, right in zip(current_numbers, candidate_numbers)
        if left == right
    ) / window_size
    wheel_path = mean(
        1.0 - (_circular_distance(left, right) / (WHEEL_SIZE // 2))
        for left, right in zip(current_indices, candidate_indices)
    )

    if current_deltas and candidate_deltas:
        delta_closeness = mean(
            1.0 - (min(abs(abs(left) - abs(right)), WHEEL_SIZE // 2) / (WHEEL_SIZE // 2))
            for left, right in zip(current_deltas, candidate_deltas)
        )
        direction_alignment = mean(
            1.0 if (left == right) else 0.0
            for left, right in zip(
                [0 if delta == 0 else (1 if delta > 0 else -1) for delta in current_deltas],
                [0 if delta == 0 else (1 if delta > 0 else -1) for delta in candidate_deltas],
            )
        )
    else:
        delta_closeness = 0.0
        direction_alignment = 0.0

    current_sector = set(current_state["hotspot"]["numbers"])
    candidate_sector = set(candidate["hotspot"]["numbers"])
    sector_overlap = len(current_sector.intersection(candidate_sector)) / max(1, HOTSPOT_WINDOW_SIZE)

    terminal_similarity = _counter_similarity(
        Counter(current_state["terminal_counts"]),
        Counter(candidate["terminal_counts"]),
        window_size,
    )
    color_similarity = _counter_similarity(
        Counter(current_state["color_counts"]),
        Counter(candidate["color_counts"]),
        window_size,
    )
    parity_similarity = _counter_similarity(
        Counter(current_state["parity_counts"]),
        Counter(candidate["parity_counts"]),
        window_size,
    )
    high_low_similarity = _counter_similarity(
        Counter(current_state["high_low_counts"]),
        Counter(candidate["high_low_counts"]),
        window_size,
    )
    dozen_similarity = _counter_similarity(
        Counter(current_state["dozen_counts"]),
        Counter(candidate["dozen_counts"]),
        window_size,
    )
    column_similarity = _counter_similarity(
        Counter(current_state["column_counts"]),
        Counter(candidate["column_counts"]),
        window_size,
    )

    attr_similarity = mean(
        [
            terminal_similarity,
            color_similarity,
            parity_similarity,
            high_low_similarity,
            dozen_similarity,
            column_similarity,
        ]
    )

    regime_intersection = len(set(current_state["active_regimes"]).intersection(candidate["active_regimes"]))
    regime_union = len(set(current_state["active_regimes"]).union(candidate["active_regimes"]))
    regime_overlap = regime_intersection / max(1, regime_union)

    hour_similarity = _hour_similarity(current_state["hour"], candidate["hour"])
    gap_similarity = _gap_similarity(current_state["avg_gap_sec"], candidate["avg_gap_sec"])

    components = {
        "number_overlap": round(number_overlap, 4),
        "position_match": round(position_match, 4),
        "wheel_path": round(wheel_path, 4),
        "delta_closeness": round(delta_closeness, 4),
        "direction_alignment": round(direction_alignment, 4),
        "sector_overlap": round(sector_overlap, 4),
        "attribute_alignment": round(attr_similarity, 4),
        "hour_similarity": round(hour_similarity, 4),
        "gap_similarity": round(gap_similarity, 4),
        "regime_overlap": round(regime_overlap, 4),
    }

    similarity = (
        0.14 * components["number_overlap"]
        + 0.06 * components["position_match"]
        + 0.18 * components["wheel_path"]
        + 0.18 * components["delta_closeness"]
        + 0.12 * components["direction_alignment"]
        + 0.10 * components["sector_overlap"]
        + 0.07 * components["attribute_alignment"]
        + 0.03 * components["hour_similarity"]
        + 0.03 * components["gap_similarity"]
        + 0.09 * components["regime_overlap"]
    )

    return {
        "similarity": round(similarity, 4),
        "components": components,
        "regime_overlap": round(regime_overlap, 4),
    }


def _select_similar_episodes(
    current_state: Dict[str, Any],
    episodes: Sequence[Dict[str, Any]],
    *,
    episode_limit: int,
    similarity_threshold: float,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    scored: List[Dict[str, Any]] = []
    for episode in episodes:
        similarity = _episode_similarity(current_state, episode)
        scored.append(
            {
                "episode": episode,
                "similarity": similarity["similarity"],
                "similarity_components": similarity["components"],
                "regime_overlap": similarity["regime_overlap"],
                "episode_weight": similarity["similarity"] * (1.0 + 0.25 * similarity["regime_overlap"]),
            }
        )

    scored.sort(key=lambda item: item["similarity"], reverse=True)
    threshold_hits = [item for item in scored if item["similarity"] >= similarity_threshold]
    fallback_needed = len(threshold_hits) < min(12, max(6, episode_limit // 4))
    selected = (scored[:episode_limit] if fallback_needed else threshold_hits[:episode_limit])
    selection_meta = {
        "selection_mode": "fallback_topn" if fallback_needed else "threshold",
        "threshold_hits": len(threshold_hits),
        "selected_count": len(selected),
        "avg_similarity": round(mean(item["similarity"] for item in selected), 4) if selected else 0.0,
    }
    return selected, selection_meta


def _transition_snapshot_from_rows(
    rows: Sequence[Dict[str, Any]],
    *,
    anchor_number: int,
) -> Dict[str, Any]:
    next_counter: Counter[int] = Counter()
    anchor_total = 0
    for idx in range(0, len(rows) - 1):
        if rows[idx]["value"] != anchor_number:
            continue
        anchor_total += 1
        next_counter[rows[idx + 1]["value"]] += 1

    top_transitions = [
        {
            "number": number,
            "count": count,
            "rate": round(count / max(1, anchor_total), 4),
        }
        for number, count in next_counter.most_common(10)
    ]
    return {
        "anchor_number": anchor_number,
        "anchor_total": anchor_total,
        "top_transitions": top_transitions,
        "raw_counter": {number: count for number, count in next_counter.items()},
    }


def _build_time_leakage(
    selected_matches: Sequence[Dict[str, Any]],
    train_episodes: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    train_hours = Counter(
        episode["state"]["hour"]
        for episode in train_episodes
        if episode["state"]["hour"] is not None
    )
    selected_hours = Counter(
        match["episode"]["state"]["hour"]
        for match in selected_matches
        if match["episode"]["state"]["hour"] is not None
    )

    total_train = max(1, sum(train_hours.values()))
    total_selected = max(1, sum(selected_hours.values()))
    rows = []
    for hour in sorted(set(train_hours) | set(selected_hours)):
        baseline_share = train_hours[hour] / total_train
        selected_share = selected_hours[hour] / total_selected
        lift = selected_share / baseline_share if baseline_share > 0 else 0.0
        rows.append(
            {
                "hour": hour,
                "matched_episodes": selected_hours[hour],
                "baseline_episodes": train_hours[hour],
                "selected_share": round(selected_share, 4),
                "baseline_share": round(baseline_share, 4),
                "lift": round(lift, 4),
            }
        )
    rows.sort(key=lambda item: (item["lift"], item["matched_episodes"]), reverse=True)
    return {
        "top_hours": rows[:6],
        "distribution": rows,
    }


def _build_regime_snapshot(
    current_state: Dict[str, Any],
    selected_matches: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    regime_counter: Counter[str] = Counter()
    for match in selected_matches:
        for label in match["episode"]["state"]["active_regimes"]:
            regime_counter[label] += 1

    distribution = [
        {
            "label": label,
            "count": count,
            "share": round(count / max(1, len(selected_matches)), 4),
        }
        for label, count in regime_counter.most_common(10)
    ]
    return {
        "current_regimes": current_state["active_regimes"],
        "matched_distribution": distribution,
        "avg_regime_overlap": round(mean(match["regime_overlap"] for match in selected_matches), 4)
        if selected_matches
        else 0.0,
    }


def _build_horizon_candidate_ranking(
    *,
    current_state: Dict[str, Any],
    selected_matches: Sequence[Dict[str, Any]],
    train_episodes: Sequence[Dict[str, Any]],
    holdout_matches: Sequence[Dict[str, Any]],
    transition_snapshot: Dict[str, Any],
    horizon: int,
    top_k: int,
) -> Dict[str, Any]:
    baseline_counter: Counter[int] = Counter()
    for episode in train_episodes:
        for number in episode["future"][:horizon]:
            baseline_counter[number] += 1
    baseline_total = max(1, len(train_episodes) * horizon)

    weight_counter: Counter[int] = Counter()
    episode_weight_hit: Counter[int] = Counter()
    similarity_hit: Counter[int] = Counter()
    regime_hit: Counter[int] = Counter()
    future_frequency: Counter[int] = Counter()
    first_positions: Dict[int, List[float]] = {number: [] for number in range(37)}
    position_hits: Dict[int, List[int]] = {number: [0] * horizon for number in range(37)}
    episode_support: Counter[int] = Counter()

    selected_total_similarity = max(EPSILON, sum(match["similarity"] for match in selected_matches))
    selected_total_episode_weight = max(EPSILON, sum(match["episode_weight"] for match in selected_matches))

    for match in selected_matches:
        future = match["episode"]["future"][:horizon]
        seen: set[int] = set()
        for pos, number in enumerate(future):
            early_weight = 1.0 / math.sqrt(pos + 1)
            weight_counter[number] += match["episode_weight"] * early_weight
            future_frequency[number] += 1
            position_hits[number][pos] += 1
            if number not in seen:
                episode_support[number] += 1
                episode_weight_hit[number] += match["episode_weight"]
                similarity_hit[number] += match["similarity"]
                regime_hit[number] += match["regime_overlap"]
                first_positions[number].append(1.0 / (pos + 1))
                seen.add(number)

    holdout_total_weight = max(EPSILON, sum(match["episode_weight"] for match in holdout_matches))
    holdout_hit_rate: Dict[int, float] = {number: 0.0 for number in range(37)}
    for number in range(37):
        weighted_hits = sum(
            match["episode_weight"]
            for match in holdout_matches
            if number in match["episode"]["future"][:horizon]
        )
        holdout_hit_rate[number] = weighted_hits / holdout_total_weight if holdout_matches else 0.0

    raw_total_weight = max(EPSILON, sum(weight_counter.values()))
    transition_counter = Counter(transition_snapshot["raw_counter"])
    anchor_total = max(1, transition_snapshot["anchor_total"])
    hotspot, cluster_metric = _build_hotspot(weight_counter)

    similarity_raw = {
        number: similarity_hit[number] / selected_total_similarity
        for number in range(37)
    }
    coverage_raw = {
        number: episode_weight_hit[number] / selected_total_episode_weight
        for number in range(37)
    }
    early_raw = {
        number: (mean(first_positions[number]) if first_positions[number] else 0.0)
        for number in range(37)
    }
    frequency_raw = {
        number: weight_counter[number] / raw_total_weight
        for number in range(37)
    }
    lift_raw = {}
    for number in range(37):
        baseline_rate = baseline_counter[number] / baseline_total
        lift_raw[number] = frequency_raw[number] / max(baseline_rate, EPSILON)
    transition_raw = {
        number: transition_counter[number] / anchor_total
        for number in range(37)
    }
    regime_raw = {
        number: (regime_hit[number] / max(1, episode_support[number]))
        for number in range(37)
    }

    similarity_metric = _normalize_metric(similarity_raw)
    coverage_metric = _normalize_metric(coverage_raw)
    early_metric = _normalize_metric(early_raw)
    lift_metric = _normalize_metric(lift_raw, cap=4.0)
    transition_metric = _normalize_metric(transition_raw)
    regime_metric = _normalize_metric(regime_raw)

    candidates: List[Dict[str, Any]] = []
    for number in range(37):
        final_score = (
            0.26 * similarity_metric[number]
            + 0.20 * coverage_metric[number]
            + 0.16 * early_metric[number]
            + 0.14 * lift_metric[number]
            + 0.10 * cluster_metric[number]
            + 0.07 * transition_metric[number]
            + 0.07 * regime_metric[number]
        )
        candidates.append(
            {
                "number": number,
                "final_score": round(final_score, 4),
                "episode_support": int(episode_support[number]),
                "future_frequency": int(future_frequency[number]),
                "holdout_hit_rate": round(holdout_hit_rate[number], 4),
                "position_hits": position_hits[number],
                "similarity_support": round(similarity_raw[number], 4),
                "coverage": round(coverage_raw[number], 4),
                "early_index": round(early_raw[number], 4),
                "frequency_rate": round(frequency_raw[number], 4),
                "lift_ratio": round(lift_raw[number], 4),
                "transition_rate": round(transition_raw[number], 4),
                "regime_support": round(regime_raw[number], 4),
                "score_components": {
                    "similarity": round(similarity_metric[number], 4),
                    "coverage": round(coverage_metric[number], 4),
                    "early": round(early_metric[number], 4),
                    "lift": round(lift_metric[number], 4),
                    "wheel_cluster": round(cluster_metric[number], 4),
                    "transition": round(transition_metric[number], 4),
                    "regime": round(regime_metric[number], 4),
                },
            }
        )

    candidates.sort(
        key=lambda item: (
            item["final_score"],
            item["episode_support"],
            item["future_frequency"],
            -item["number"],
        ),
        reverse=True,
    )
    return {
        "horizon": horizon,
        "hotspot": hotspot,
        "candidates": candidates[:top_k],
    }


def _label_confidence(score: int) -> str:
    if score >= 78:
        return "Alta"
    if score >= 58:
        return "Média"
    if score >= 38:
        return "Baixa"
    return "Muito baixa"


def _build_suggestion(
    *,
    current_state: Dict[str, Any],
    primary_ranking: Dict[str, Any],
    selected_matches: Sequence[Dict[str, Any]],
    holdout_matches: Sequence[Dict[str, Any]],
    min_support: int,
) -> Dict[str, Any]:
    top_candidates = list(primary_ranking["candidates"])
    if not top_candidates:
        return {
            "available": False,
            "primary_numbers": [],
            "secondary_numbers": [],
            "confidence": {"score": 0, "label": "Muito baixa"},
            "rationale": ["Sem episódios parecidos suficientes para montar a previsão."],
        }

    top_score = max(top_candidates[0]["final_score"], EPSILON)
    primary = [
        candidate["number"]
        for candidate in top_candidates
        if candidate["final_score"] >= top_score * 0.75
    ][:5]
    if len(primary) < 4:
        primary = [candidate["number"] for candidate in top_candidates[:4]]

    secondary = [
        candidate["number"]
        for candidate in top_candidates
        if candidate["number"] not in primary and candidate["final_score"] >= top_score * 0.50
    ][:6]

    support_score = min(1.0, len(selected_matches) / max(min_support * 4, 10))
    avg_similarity = mean(match["similarity"] for match in selected_matches) if selected_matches else 0.0
    regime_coherence = mean(match["regime_overlap"] for match in selected_matches) if selected_matches else 0.0
    top_mass = (
        sum(candidate["final_score"] for candidate in top_candidates[:4])
        / max(EPSILON, sum(candidate["final_score"] for candidate in top_candidates[:10]))
    )
    if holdout_matches:
        holdout_primary = sum(
            match["episode_weight"]
            for match in holdout_matches
            if any(number in match["episode"]["future"][:primary_ranking["horizon"]] for number in primary)
        ) / max(EPSILON, sum(match["episode_weight"] for match in holdout_matches))
    else:
        holdout_primary = 0.5 if len(selected_matches) >= min_support else 0.0

    confidence_score = round(
        100.0
        * (
            0.30 * support_score
            + 0.25 * avg_similarity
            + 0.20 * top_mass
            + 0.15 * holdout_primary
            + 0.10 * regime_coherence
        )
    )

    rationale = [
        f"Estado atual: {', '.join(str(number) for number in current_state['numbers'])}.",
        f"{len(selected_matches)} episódios parecidos entraram no ensemble.",
        f"Similaridade média dos episódios: {avg_similarity:.2%}.",
        f"Regimes ativos: {', '.join(current_state['active_regimes'])}.",
        f"Validação em holdout do bloco principal: {holdout_primary:.2%}.",
    ]
    if len(selected_matches) < min_support:
        rationale.append("Suporte abaixo do mínimo desejado; tratar como hipótese exploratória.")

    return {
        "available": bool(primary) and len(selected_matches) >= 3,
        "primary_numbers": primary,
        "secondary_numbers": secondary,
        "confidence": {
            "score": confidence_score,
            "label": _label_confidence(confidence_score),
        },
        "rationale": rationale,
    }


def _empty_analysis(
    *,
    roulette_id: str,
    state_numbers: Sequence[int],
    state_window: int,
    future_horizon: int,
    episode_limit: int,
    similarity_threshold: float,
    total_spins_analyzed: int,
    message: str,
) -> Dict[str, Any]:
    return {
        "summary": {
            "roulette_id": roulette_id,
            "state_numbers": list(state_numbers),
            "state_window": state_window,
            "future_horizon": future_horizon,
            "episode_limit": episode_limit,
            "similarity_threshold": similarity_threshold,
            "total_spins_analyzed": total_spins_analyzed,
            "total_episodes": 0,
            "train_episodes": 0,
            "holdout_episodes": 0,
            "matched_episodes": 0,
            "selection_mode": "none",
        },
        "current_state": {
            "source": "manual" if state_numbers else "none",
            "numbers": list(state_numbers),
            "active_regimes": [],
            "hotspot": {"center": None, "numbers": [], "sector_sum": 0.0, "window_size": HOTSPOT_WINDOW_SIZE},
        },
        "suggestion": {
            "available": False,
            "primary_numbers": [],
            "secondary_numbers": [],
            "confidence": {"score": 0, "label": "Muito baixa"},
            "rationale": [message],
        },
        "regime_snapshot": {"current_regimes": [], "matched_distribution": [], "avg_regime_overlap": 0.0},
        "time_leakage": {"top_hours": [], "distribution": []},
        "transition_snapshot": {"anchor_number": None, "anchor_total": 0, "top_transitions": [], "raw_counter": {}},
        "horizon_rankings": {},
        "top_candidates": [],
        "similar_episodes": [],
        "recent_episode_excluded": None,
        "validation_snapshot": {"holdout_matches": 0, "avg_similarity": 0.0},
    }


def build_decoder_lab_analysis(
    rows: Sequence[Dict[str, Any]],
    *,
    roulette_id: str,
    state_numbers: Sequence[int] | None = None,
    state_window: int = DEFAULT_STATE_WINDOW,
    future_horizon: int = DEFAULT_FUTURE_HORIZON,
    ignore_last_occurrence: bool = True,
    validation_ratio: float = DEFAULT_VALIDATION_RATIO,
    min_support: int = 3,
    top_k: int = DEFAULT_TOP_K,
    episode_limit: int = DEFAULT_EPISODE_LIMIT,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> Dict[str, Any]:
    normalized_rows = _normalize_rows(rows)
    manual_state = [int(number) for number in (state_numbers or [])]
    effective_state_window = len(manual_state) if manual_state else max(2, int(state_window))
    if effective_state_window < 2:
        raise ValueError("state_window deve ser maior ou igual a 2.")
    if future_horizon <= 0:
        raise ValueError("future_horizon deve ser maior que zero.")

    if not normalized_rows and not manual_state:
        return _empty_analysis(
            roulette_id=roulette_id,
            state_numbers=[],
            state_window=effective_state_window,
            future_horizon=future_horizon,
            episode_limit=episode_limit,
            similarity_threshold=similarity_threshold,
            total_spins_analyzed=0,
            message="Sem histórico disponível para montar o estado atual.",
        )

    current_state = _build_current_state(
        normalized_rows,
        state_numbers=manual_state,
        state_window=effective_state_window,
    )
    max_horizon = max({future_horizon, *DEFAULT_HORIZON_SET})
    episode_bank = _build_episode_bank(
        normalized_rows,
        state_window=len(current_state["numbers"]),
        max_horizon=max_horizon,
    )

    if not episode_bank:
        return {
            **_empty_analysis(
                roulette_id=roulette_id,
                state_numbers=current_state["numbers"],
                state_window=len(current_state["numbers"]),
                future_horizon=future_horizon,
                episode_limit=episode_limit,
                similarity_threshold=similarity_threshold,
                total_spins_analyzed=len(normalized_rows),
                message="Histórico insuficiente para formar episódios com futuro observável.",
            ),
            "current_state": current_state,
            "transition_snapshot": _transition_snapshot_from_rows(
                normalized_rows,
                anchor_number=current_state["numbers"][-1],
            ),
        }

    train_episodes, holdout_episodes = _split_episode_bank(
        episode_bank,
        validation_ratio=validation_ratio,
    )
    recent_episode_excluded = None
    if ignore_last_occurrence and len(train_episodes) > 1:
        excluded = train_episodes.pop()
        recent_episode_excluded = {
            "end_timestamp": excluded["end_timestamp"],
            "state_numbers": excluded["state"]["numbers"],
            "future": excluded["future"][:future_horizon],
        }

    selected_matches, selection_meta = _select_similar_episodes(
        current_state,
        train_episodes,
        episode_limit=episode_limit,
        similarity_threshold=similarity_threshold,
    )
    holdout_matches, holdout_meta = _select_similar_episodes(
        current_state,
        holdout_episodes,
        episode_limit=min(25, max(8, episode_limit // 2)),
        similarity_threshold=max(0.45, similarity_threshold * 0.9),
    ) if holdout_episodes else ([], {"selected_count": 0, "avg_similarity": 0.0, "selection_mode": "none", "threshold_hits": 0})

    transition_snapshot = _transition_snapshot_from_rows(
        normalized_rows,
        anchor_number=current_state["numbers"][-1],
    )

    if not selected_matches:
        return {
            "summary": {
                "roulette_id": roulette_id,
                "state_numbers": current_state["numbers"],
                "state_window": len(current_state["numbers"]),
                "future_horizon": future_horizon,
                "episode_limit": episode_limit,
                "similarity_threshold": similarity_threshold,
                "total_spins_analyzed": len(normalized_rows),
                "total_episodes": len(episode_bank),
                "train_episodes": len(train_episodes),
                "holdout_episodes": len(holdout_episodes),
                "matched_episodes": 0,
                "selection_mode": selection_meta["selection_mode"],
            },
            "current_state": current_state,
            "suggestion": {
                "available": False,
                "primary_numbers": [],
                "secondary_numbers": [],
                "confidence": {"score": 0, "label": "Muito baixa"},
                "rationale": ["Nenhum episódio histórico ficou próximo o suficiente do estado atual."],
            },
            "regime_snapshot": _build_regime_snapshot(current_state, []),
            "time_leakage": _build_time_leakage([], train_episodes),
            "transition_snapshot": transition_snapshot,
            "horizon_rankings": {},
            "top_candidates": [],
            "similar_episodes": [],
            "recent_episode_excluded": recent_episode_excluded,
            "validation_snapshot": {
                "holdout_matches": holdout_meta["selected_count"],
                "avg_similarity": holdout_meta["avg_similarity"],
            },
        }

    horizons = sorted({future_horizon, *DEFAULT_HORIZON_SET})
    horizons = [horizon for horizon in horizons if horizon <= max_horizon]

    horizon_rankings: Dict[str, Any] = {}
    for horizon in horizons:
        ranking = _build_horizon_candidate_ranking(
            current_state=current_state,
            selected_matches=selected_matches,
            train_episodes=train_episodes,
            holdout_matches=holdout_matches,
            transition_snapshot=transition_snapshot,
            horizon=horizon,
            top_k=max(top_k, 8),
        )
        horizon_rankings[str(horizon)] = ranking

    primary_ranking = horizon_rankings[str(future_horizon)]
    suggestion = _build_suggestion(
        current_state=current_state,
        primary_ranking=primary_ranking,
        selected_matches=selected_matches,
        holdout_matches=holdout_matches,
        min_support=min_support,
    )

    similar_episodes = [
        {
            "end_timestamp": match["episode"]["end_timestamp"],
            "state_numbers": match["episode"]["state"]["numbers"],
            "future_numbers": match["episode"]["future"][:future_horizon],
            "similarity": match["similarity"],
            "regime_overlap": match["regime_overlap"],
            "active_regimes": match["episode"]["state"]["active_regimes"],
            "similarity_components": match["similarity_components"],
        }
        for match in selected_matches[:20]
    ]

    summary = {
        "roulette_id": roulette_id,
        "state_numbers": current_state["numbers"],
        "state_window": len(current_state["numbers"]),
        "future_horizon": future_horizon,
        "episode_limit": episode_limit,
        "similarity_threshold": similarity_threshold,
        "total_spins_analyzed": len(normalized_rows),
        "total_episodes": len(episode_bank),
        "train_episodes": len(train_episodes),
        "holdout_episodes": len(holdout_episodes),
        "matched_episodes": len(selected_matches),
        "selection_mode": selection_meta["selection_mode"],
    }

    return {
        "summary": summary,
        "current_state": current_state,
        "suggestion": suggestion,
        "regime_snapshot": _build_regime_snapshot(current_state, selected_matches),
        "time_leakage": _build_time_leakage(selected_matches, train_episodes),
        "transition_snapshot": transition_snapshot,
        "horizon_rankings": horizon_rankings,
        "top_candidates": primary_ranking["candidates"][:top_k],
        "similar_episodes": similar_episodes,
        "recent_episode_excluded": recent_episode_excluded,
        "validation_snapshot": {
            "holdout_matches": len(holdout_matches),
            "avg_similarity": holdout_meta["avg_similarity"],
        },
    }


async def load_decoder_lab_rows(
    *,
    roulette_id: str,
    days_back: int = DEFAULT_DAYS_BACK,
    max_records: int = DEFAULT_MAX_RECORDS,
) -> List[Dict[str, Any]]:
    query: Dict[str, Any] = {"roulette_id": roulette_id}
    if days_back > 0:
        query["timestamp"] = {"$gte": datetime.utcnow() - timedelta(days=days_back)}

    cursor = history_coll.find(query, {"_id": 0, "value": 1, "timestamp": 1}).sort("timestamp", -1)
    if max_records > 0:
        cursor = cursor.limit(max_records)

    rows = await cursor.to_list(length=max_records if max_records > 0 else None)
    rows.reverse()
    return rows

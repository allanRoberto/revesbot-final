from __future__ import annotations

import math
from typing import Any, Dict, List, Set


ROULETTE_EUROPEAN_NUMBERS: List[int] = [
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23,
    10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26,
]

SECTION_MAP: Dict[str, List[int]] = {
    "Jeu Zero": [12, 35, 3, 26, 0, 32, 15],
    "Voisins": [22, 18, 29, 7, 28, 12, 35, 3, 26, 0, 32, 15, 19, 4, 21, 2, 25],
    "Orphelins": [17, 34, 6, 1, 20, 14, 31, 9],
    "Tiers": [27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33],
}

RED_NUMBERS: Set[int] = {
    1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36,
}


def _js_round(value: float) -> int:
    if value >= 0:
        return int(math.floor(value + 0.5))
    return int(math.ceil(value - 0.5))


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def normalize_weights(base_weight: float, optimized_weight: float) -> tuple[float, float]:
    b = _clamp(float(base_weight), 0.0, 1.0)
    o = _clamp(float(optimized_weight), 0.0, 1.0)
    total = b + o
    if total > 0:
        return (b / total, o / total)
    return (0.5, 0.5)


def get_dozen(n: int) -> str:
    if n == 0:
        return "Zero"
    if n <= 12:
        return "1ª"
    if n <= 24:
        return "2ª"
    return "3ª"


def get_column(n: int) -> str:
    if n == 0:
        return "Zero"
    col = (n - 1) % 3
    if col == 0:
        return "C1"
    if col == 1:
        return "C2"
    return "C3"


def get_highlow(n: int) -> str:
    if n == 0:
        return "Zero"
    return "Baixo" if n <= 18 else "Alto"


def get_parity(n: int) -> str:
    if n == 0:
        return "Zero"
    return "Par" if (n % 2 == 0) else "Ímpar"


def get_color_label(n: int) -> str:
    if n == 0:
        return "green"
    return "red" if n in RED_NUMBERS else "black"


def get_sections(n: int) -> List[str]:
    found: List[str] = []
    for name, nums in SECTION_MAP.items():
        if n in nums:
            found.append(name)
    return found if found else ["—"]


def sum_digits(n: int) -> int:
    return sum(int(ch) for ch in str(abs(int(n))))


def get_neighbors(num: int) -> List[int]:
    # Mantém a regra específica do frontend.
    if num == 26:
        return [3, 35]
    if num == 32:
        return [15, 19]
    try:
        idx = ROULETTE_EUROPEAN_NUMBERS.index(num)
    except ValueError:
        return []
    left = ROULETTE_EUROPEAN_NUMBERS[(idx - 1 + len(ROULETTE_EUROPEAN_NUMBERS)) % len(ROULETTE_EUROPEAN_NUMBERS)]
    right = ROULETTE_EUROPEAN_NUMBERS[(idx + 1) % len(ROULETTE_EUROPEAN_NUMBERS)]
    return [left, right]


def build_focus_context(history: List[int], focus_number: int, from_index: int) -> Dict[str, Any]:
    occurrences: List[int] = []
    for i in range(max(0, from_index), len(history)):
        if history[i] == focus_number:
            occurrences.append(i)

    pulled: List[int] = []
    for idx in occurrences:
        if idx - 1 >= from_index:
            pulled.append(history[idx - 1])

    pulled_counts: Dict[int, int] = {}
    for n in pulled:
        pulled_counts[n] = pulled_counts.get(n, 0) + 1

    bucket = {
        "dozen": {"1ª": 0, "2ª": 0, "3ª": 0, "Zero": 0},
        "column": {"C1": 0, "C2": 0, "C3": 0, "Zero": 0},
        "highlow": {"Baixo": 0, "Alto": 0, "Zero": 0},
        "parity": {"Par": 0, "Ímpar": 0, "Zero": 0},
        "color": {"red": 0, "black": 0, "green": 0},
        "section": {"Jeu Zero": 0, "Voisins": 0, "Orphelins": 0, "Tiers": 0},
        "horse": {"147": 0, "258": 0, "036": 0, "369": 0},
    }

    for n in pulled:
        bucket["dozen"][get_dozen(n)] += 1
        bucket["column"][get_column(n)] += 1
        bucket["highlow"][get_highlow(n)] += 1
        bucket["parity"][get_parity(n)] += 1
        bucket["color"][get_color_label(n)] += 1
        for section in get_sections(n):
            if section in bucket["section"]:
                bucket["section"][section] += 1
        terminal = n % 10
        if terminal in {1, 4, 7}:
            bucket["horse"]["147"] += 1
        if terminal in {2, 5, 8}:
            bucket["horse"]["258"] += 1
        if terminal in {0, 3, 6}:
            bucket["horse"]["036"] += 1
        if terminal in {3, 6, 9}:
            bucket["horse"]["369"] += 1

    return {
        "occurrences": occurrences,
        "pulled": pulled,
        "pulled_counts": pulled_counts,
        "bucket": bucket,
    }


def compute_confidence(bucket: Dict[str, Dict[str, int]], total_pulled: int) -> Dict[str, Any]:
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
    avg = (sum(ratios) / len(ratios)) if ratios else 0.0
    volume_factor = min(1.0, total_pulled / 15.0)
    score = _js_round(avg * volume_factor * 100.0)
    label = confidence_label_from_score(score)
    return {"score": score, "label": label}


def confidence_label_from_score(score: int) -> str:
    if score >= 70:
        return "Alta"
    if score >= 50:
        return "Média"
    return "Baixa"


def _resolve_assertive_target_size(
    requested_target_size: int,
    effective_optimized_confidence: int,
    intersection_count: int,
) -> tuple[int, List[str]]:
    target_size = max(1, int(requested_target_size))
    reasons: List[str] = []

    if target_size <= 9:
        return target_size, reasons

    resolved = target_size
    if effective_optimized_confidence < 50:
        resolved = min(resolved, 8)
        reasons.append("confidence_lt_50")
    elif effective_optimized_confidence < 60:
        resolved = min(resolved, 9)
        reasons.append("confidence_lt_60")

    if intersection_count <= 3 and effective_optimized_confidence < 70:
        resolved = min(resolved, max(6, target_size - 2))
        reasons.append("low_intersection")

    return max(1, resolved), reasons


def _circular_distance_on_wheel(a_idx: int, b_idx: int) -> int:
    wheel_len = len(ROULETTE_EUROPEAN_NUMBERS)
    raw = abs(a_idx - b_idx)
    return min(raw, wheel_len - raw)


def _build_wheel_heat_score(window_arr: List[int]) -> Dict[int, float]:
    idx_map = {n: i for i, n in enumerate(ROULETTE_EUROPEAN_NUMBERS)}
    wheel_len = len(ROULETTE_EUROPEAN_NUMBERS)
    scores: Dict[int, float] = {n: 0.0 for n in range(37)}

    def add(index: int, amount: float) -> None:
        num = ROULETTE_EUROPEAN_NUMBERS[(index + wheel_len) % wheel_len]
        scores[num] = float(scores.get(num, 0.0)) + amount

    for num in window_arr:
        idx = idx_map.get(num)
        if idx is None:
            continue
        add(idx, 1.0)
        add(idx - 1, 0.65)
        add(idx + 1, 0.65)
        add(idx - 2, 0.35)
        add(idx + 2, 0.35)

    return scores


def _analyze_sector_signal(source_arr: List[int], from_index: int = 0, window: int = 20) -> Dict[str, Any]:
    segment = [n for n in source_arr[from_index:from_index + window] if isinstance(n, int)]
    if len(segment) < 8:
        return {
            "alternation_active": False,
            "target_zone": set(),
            "cold_numbers": set(),
        }

    score_map = _build_wheel_heat_score(segment)
    idx_map = {n: i for i, n in enumerate(ROULETTE_EUROPEAN_NUMBERS)}
    ranked_hot = sorted(
        ({"n": int(n), "s": float(s)} for n, s in score_map.items()),
        key=lambda item: (-item["s"], item["n"]),
    )

    centers: List[int] = []
    for item in ranked_hot:
        idx = idx_map.get(item["n"])
        if idx is None:
            continue
        far_enough = True
        for c in centers:
            c_idx = idx_map.get(c)
            if c_idx is None:
                continue
            if _circular_distance_on_wheel(idx, c_idx) < 6:
                far_enough = False
                break
        if far_enough:
            centers.append(item["n"])
        if len(centers) >= 2:
            break

    alternation_active = False
    target_zone: Set[int] = set()
    if len(centers) >= 2:
        a = centers[0]
        b = centers[1]
        a_idx = idx_map[a]
        b_idx = idx_map[b]
        labels: List[str] = []
        for n in segment:
            i = idx_map.get(n)
            if i is None:
                labels.append("A")
            else:
                da = _circular_distance_on_wheel(i, a_idx)
                db = _circular_distance_on_wheel(i, b_idx)
                labels.append("A" if da <= db else "B")

        switches = 0
        for i in range(len(labels) - 1):
            if labels[i + 1] != labels[i]:
                switches += 1
        ratio = (switches / (len(labels) - 1)) if len(labels) > 1 else 0.0
        alternation_active = ratio >= 0.45

        if alternation_active:
            latest_label = labels[0]
            target_center = b if latest_label == "A" else a
            target_idx = idx_map[target_center]
            for d in range(-2, 3):
                target_zone.add(ROULETTE_EUROPEAN_NUMBERS[(target_idx + d + len(ROULETTE_EUROPEAN_NUMBERS)) % len(ROULETTE_EUROPEAN_NUMBERS)])

    sorted_cold = sorted(
        ({"n": int(n), "s": float(s)} for n, s in score_map.items()),
        key=lambda item: (item["s"], item["n"]),
    )
    cold_numbers = {item["n"] for item in sorted_cold[:12]}
    return {
        "alternation_active": alternation_active,
        "target_zone": target_zone,
        "cold_numbers": cold_numbers,
    }


def _analyze_local_transition_protection(source_arr: List[int], from_index: int = 0, window: int = 500) -> Dict[str, Any]:
    if from_index >= len(source_arr):
        return {"active": False, "boosts": {}}
    current = source_arr[from_index]
    if not isinstance(current, int):
        return {"active": False, "boosts": {}}

    start = from_index + 1
    end = min(len(source_arr) - 1, from_index + max(50, window))
    if start > end:
        return {"active": False, "boosts": {}}

    occurrences = 0
    total_transitions = 0
    transition_counts: Dict[int, int] = {}
    baseline_counts: Dict[int, int] = {}

    for idx in range(start, end + 1):
        next_num = source_arr[idx - 1]
        if not isinstance(next_num, int):
            continue
        baseline_counts[next_num] = baseline_counts.get(next_num, 0) + 1
        total_transitions += 1
        if source_arr[idx] == current:
            occurrences += 1
            transition_counts[next_num] = transition_counts.get(next_num, 0) + 1

    if occurrences < 6 or total_transitions <= 0:
        return {"active": False, "boosts": {}}

    candidates: Dict[int, float] = {}
    for n, w in ((current, 1.0), (current - 1, 0.85), (current + 1, 0.85), (sum_digits(current), 0.8)):
        if isinstance(n, int) and 0 <= n <= 36:
            candidates[n] = max(candidates.get(n, 0.0), w)

    boosts: Dict[int, float] = {}
    evidence = max(1.0, min(2.0, occurrences / 8.0))
    for n, base_w in candidates.items():
        cond_hits = transition_counts.get(n, 0)
        if cond_hits <= 0:
            continue
        cond_prob = cond_hits / occurrences
        base_prob = baseline_counts.get(n, 0) / total_transitions
        lift = (cond_prob / base_prob) if base_prob > 0 else 2.0
        if lift < 1.2:
            continue
        boosts[n] = base_w * lift * evidence

    return {"active": len(boosts) > 0, "boosts": boosts}


def _analyze_siege_signal(
    source_arr: List[int],
    from_index: int = 0,
    siege_window: int = 6,
    siege_min_occurrences: int = 3,
    siege_min_streak: int = 2,
) -> Dict[str, Any]:
    if from_index >= len(source_arr):
        return {"active": False, "strong_set": set(), "scores": {}}
    current = source_arr[from_index]
    if not isinstance(current, int):
        return {"active": False, "strong_set": set(), "scores": {}}

    current_candidates = {
        n for n in (current, current - 1, current + 1, sum_digits(current))
        if isinstance(n, int) and 0 <= n <= 36
    }

    window_sets: List[Set[int]] = []
    end = min(len(source_arr) - 1, from_index + max(2, int(siege_window)))
    for cursor in range(from_index + 1, end + 1):
        anchor = source_arr[cursor]
        if not isinstance(anchor, int):
            continue
        s = {
            n for n in (anchor, anchor - 1, anchor + 1, sum_digits(anchor))
            if isinstance(n, int) and 0 <= n <= 36
        }
        window_sets.append(s)

    if not window_sets:
        return {"active": False, "strong_set": set(), "scores": {}}

    freq: Dict[int, int] = {}
    for s in window_sets:
        for n in s:
            freq[n] = freq.get(n, 0) + 1

    scores: Dict[int, float] = {}
    strong_set: Set[int] = set()
    for n in current_candidates:
        f = freq.get(n, 0)
        if f < int(siege_min_occurrences):
            continue
        streak = 0
        for s in window_sets:
            if n in s:
                streak += 1
            else:
                break
        if streak < int(siege_min_streak):
            continue
        score = (f * 0.7) + (streak * 0.45)
        scores[n] = score
        strong_set.add(n)

    return {
        "active": len(strong_set) > 0,
        "strong_set": strong_set,
        "scores": scores,
    }


def build_base_suggestion(
    bucket: Dict[str, Dict[str, int]],
    pulled_counts: Dict[int, int],
    total_pulled: int,
    source_arr: List[int],
    from_index: int = 0,
    siege_window: int = 6,
    siege_min_occurrences: int = 3,
    siege_min_streak: int = 2,
    siege_veto_relief: float = 0.4,
    preserve_ranking: bool = False,
) -> List[int]:
    if total_pulled <= 0:
        return []

    def dominant(obj: Dict[str, int], min_ratio: float = 0.6, min_count: int = 3) -> Dict[str, Any] | None:
        items = list(obj.items())
        if not items:
            return None
        key, val = sorted(items, key=lambda x: x[1], reverse=True)[0]
        if not val or val < min_count:
            return None
        ratio = val / total_pulled
        return {"key": key, "ratio": ratio} if ratio >= min_ratio else None

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

    def apply_filter(p: Dict[str, Any]) -> None:
        nonlocal base
        pick = p.get("pick")
        if not pick:
            return
        key = str(pick.get("key"))
        ptype = str(p.get("type"))
        if ptype == "dozen":
            if key == "1ª":
                base = [n for n in base if 1 <= n <= 12]
            if key == "2ª":
                base = [n for n in base if 13 <= n <= 24]
            if key == "3ª":
                base = [n for n in base if 25 <= n <= 36]
        elif ptype == "section" and key in SECTION_MAP:
            section_nums = set(SECTION_MAP[key])
            base = [n for n in base if n in section_nums]
        elif ptype == "column":
            if key == "C1":
                col_nums = {n for n in range(1, 37) if ((n - 1) % 3) == 0}
            elif key == "C2":
                col_nums = {n for n in range(1, 37) if ((n - 1) % 3) == 1}
            else:
                col_nums = {n for n in range(1, 37) if ((n - 1) % 3) == 2}
            base = [n for n in base if n in col_nums]
        elif ptype == "highlow":
            base = [n for n in base if (n <= 18 if key == "Baixo" else n >= 19)]
        elif ptype == "parity":
            base = [n for n in base if ((n % 2 == 0) if key == "Par" else (n % 2 == 1))]
        elif ptype == "color":
            base = [n for n in base if get_color_label(n) == key]

    for p in picks:
        apply_filter(p)

    if not base and picks:
        relaxed = sorted(picks, key=lambda p: float(p.get("pick", {}).get("ratio", 0.0)))
        base = list(range(1, 37))
        for p in relaxed[1:]:
            apply_filter(p)

    candidates: List[int]
    if (not base) or (len(base) == 36):
        top_pulled = sorted(pulled_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:12]
        if not top_pulled:
            return []
        candidates = [int(n) for n, _ in top_pulled]
    else:
        sorted_base = sorted(base)
        if len(sorted_base) == 1:
            n = sorted_base[0]
            candidates = list(dict.fromkeys([n] + get_neighbors(n)))
        else:
            candidates = sorted_base

    sector_signal = _analyze_sector_signal(source_arr, from_index, 50)
    local_protection = _analyze_local_transition_protection(source_arr, from_index, 500)
    siege_signal = _analyze_siege_signal(
        source_arr,
        from_index,
        siege_window=siege_window,
        siege_min_occurrences=siege_min_occurrences,
        siege_min_streak=siege_min_streak,
    )

    def score_candidate(n: int) -> float:
        score = 0.0
        pulled = pulled_counts.get(n, 0)
        is_pulled = pulled > 0
        score += (pulled * 1.2) if is_pulled else 0.0
        if sector_signal["alternation_active"] and n in sector_signal["target_zone"]:
            score += 2.4
        if not is_pulled:
            cold_penalty = 2.1 if n in sector_signal["cold_numbers"] else 0.0
            if siege_signal["active"] and n in siege_signal["strong_set"]:
                cold_penalty = cold_penalty * max(0.0, 1.0 - float(siege_veto_relief))
            score -= cold_penalty
        if local_protection["active"] and n in local_protection["boosts"]:
            score += float(local_protection["boosts"][n])
        if siege_signal["active"] and n in siege_signal["scores"]:
            score += float(siege_signal["scores"][n])
        return score

    ranked = sorted(
        {n for n in candidates if isinstance(n, int) and 0 <= n <= 36},
        key=lambda n: (-score_candidate(n), n),
    )
    top = ranked[:12]
    if preserve_ranking:
        return top
    return sorted(top)


def analyze_inversion_context(
    suggestion_list: List[int],
    history_arr: List[int],
    from_index: int,
    window_size: int = 15,
) -> Dict[str, Any]:
    inverted_numbers: Set[int] = set()
    inverted_details: List[Dict[str, Any]] = []
    if (not suggestion_list) or (not history_arr):
        return {"inverted_numbers": inverted_numbers, "inverted_details": inverted_details}
    if from_index < 0 or (from_index + 1) >= len(history_arr):
        return {"inverted_numbers": inverted_numbers, "inverted_details": inverted_details}

    suggestion_set = {int(n) for n in suggestion_list if isinstance(n, int)}
    start = from_index + 1
    end = min(len(history_arr), from_index + 1 + int(window_size))
    for i in range(start, end):
        num = history_arr[i]
        if not isinstance(num, int):
            continue
        if num in suggestion_set:
            inverted_numbers.add(num)
            inverted_details.append(
                {
                    "number": num,
                    "position": i - from_index,
                    "index": i,
                }
            )
    return {"inverted_numbers": inverted_numbers, "inverted_details": inverted_details}


def find_protections(suggestion_list: List[int]) -> List[int]:
    if not suggestion_list or len(suggestion_list) < 2:
        return []
    suggestion_set = {int(n) for n in suggestion_list if isinstance(n, int)}
    protections: Set[int] = set()
    wheel_len = len(ROULETTE_EUROPEAN_NUMBERS)

    for raw in suggestion_list:
        n = int(raw)
        try:
            idx = ROULETTE_EUROPEAN_NUMBERS.index(n)
        except ValueError:
            continue

        right_neighbor = ROULETTE_EUROPEAN_NUMBERS[(idx + 1) % wheel_len]
        right_neighbor2 = ROULETTE_EUROPEAN_NUMBERS[(idx + 2) % wheel_len]
        if (right_neighbor2 in suggestion_set) and (right_neighbor not in suggestion_set):
            protections.add(right_neighbor)

        left_neighbor = ROULETTE_EUROPEAN_NUMBERS[(idx - 1 + wheel_len) % wheel_len]
        left_neighbor2 = ROULETTE_EUROPEAN_NUMBERS[(idx - 2 + wheel_len) % wheel_len]
        if (left_neighbor2 in suggestion_set) and (left_neighbor not in suggestion_set):
            protections.add(left_neighbor)

    return sorted(protections)


def _wheel_neighbor(number: int, offset: int) -> int | None:
    try:
        idx = ROULETTE_EUROPEAN_NUMBERS.index(int(number))
    except ValueError:
        return None
    wheel_len = len(ROULETTE_EUROPEAN_NUMBERS)
    return ROULETTE_EUROPEAN_NUMBERS[(idx + offset) % wheel_len]


def _is_isolated_on_wheel(selected_set: Set[int], number: int) -> bool:
    left = _wheel_neighbor(number, -1)
    right = _wheel_neighbor(number, 1)
    return bool(left not in selected_set and right not in selected_set)


def _estimate_block_candidate_score(
    number: int,
    selected_set: Set[int],
    score_map: Dict[int, float],
    pulled_counts: Dict[int, int],
) -> float:
    if number in score_map:
        return float(score_map[number])

    score = float(pulled_counts.get(number, 0) or 0) * 0.5
    for offset, weight in ((-1, 0.92), (1, 0.92), (-2, 0.38), (2, 0.38)):
        neighbor = _wheel_neighbor(number, offset)
        if neighbor in selected_set:
            score += float(score_map.get(neighbor, 0.0)) * weight
    return score


def _pick_lowest_ranked_for_block_swap(
    *,
    selected_set: Set[int],
    score_map: Dict[int, float],
    protected_set: Set[int],
    count: int,
) -> List[int]:
    candidates = [n for n in selected_set if n not in protected_set]
    candidates.sort(
        key=lambda n: (
            1 if not _is_isolated_on_wheel(selected_set, n) else 0,
            sum(1 for neighbor in (_wheel_neighbor(n, -1), _wheel_neighbor(n, 1)) if neighbor in selected_set),
            float(score_map.get(n, 0.0)),
            int(n),
        )
    )
    return candidates[:count]


def _compact_final_list_into_blocks(
    initial_list: List[int],
    score_map: Dict[int, float],
    pulled_counts: Dict[int, int],
    target_size: int,
) -> Dict[str, Any]:
    selected_set: Set[int] = {int(n) for n in initial_list if isinstance(n, int)}
    if target_size <= 1 or len(selected_set) <= 1:
        ordered = sorted(selected_set, key=lambda n: (-float(score_map.get(n, 0.0)), int(n)))
        return {
            "list": ordered[:target_size],
            "added": [],
            "removed": [],
            "changed": False,
        }

    added_numbers: List[int] = []
    removed_numbers: List[int] = []

    def swap_in(candidate_numbers: List[int], protected_set: Set[int]) -> bool:
        normalized_candidates = []
        for raw in candidate_numbers:
            try:
                n = int(raw)
            except (TypeError, ValueError):
                continue
            if 0 <= n <= 36 and n not in selected_set and n not in normalized_candidates:
                normalized_candidates.append(n)
        if not normalized_candidates:
            return False

        removals = _pick_lowest_ranked_for_block_swap(
            selected_set=selected_set,
            score_map=score_map,
            protected_set=set(protected_set).union(normalized_candidates),
            count=len(normalized_candidates),
        )
        if len(removals) != len(normalized_candidates):
            return False

        candidate_scores = {
            n: _estimate_block_candidate_score(n, selected_set, score_map, pulled_counts)
            for n in normalized_candidates
        }

        for n in removals:
            selected_set.remove(n)
            removed_numbers.append(n)

        for n in normalized_candidates:
            selected_set.add(n)
            score_map[n] = candidate_scores[n]
            added_numbers.append(n)

        return True

    max_iterations = len(ROULETTE_EUROPEAN_NUMBERS) * 2
    iterations = 0
    changed = False

    while iterations < max_iterations:
        iterations += 1
        iteration_changed = False

        gap_candidates: List[Dict[str, Any]] = []
        for idx, number in enumerate(ROULETTE_EUROPEAN_NUMBERS):
            if number in selected_set:
                continue
            left = ROULETTE_EUROPEAN_NUMBERS[(idx - 1) % len(ROULETTE_EUROPEAN_NUMBERS)]
            right = ROULETTE_EUROPEAN_NUMBERS[(idx + 1) % len(ROULETTE_EUROPEAN_NUMBERS)]
            if left in selected_set and right in selected_set:
                score = _estimate_block_candidate_score(number, selected_set, score_map, pulled_counts) + 0.2
                gap_candidates.append(
                    {
                        "number": number,
                        "protected": {left, right},
                        "score": score,
                    }
                )

        gap_candidates.sort(key=lambda item: (-float(item["score"]), int(item["number"])))
        for candidate in gap_candidates:
            number = int(candidate["number"])
            protected = set(candidate["protected"])
            if number in selected_set or not protected.issubset(selected_set):
                continue
            if swap_in([number], protected):
                iteration_changed = True
                changed = True
                break

        if iteration_changed:
            continue

        isolated_numbers = sorted(
            [n for n in selected_set if _is_isolated_on_wheel(selected_set, n)],
            key=lambda n: (-float(score_map.get(n, 0.0)), int(n)),
        )
        for anchor in isolated_numbers:
            if anchor not in selected_set or not _is_isolated_on_wheel(selected_set, anchor):
                continue
            neighbor_candidates = []
            for neighbor in (_wheel_neighbor(anchor, -1), _wheel_neighbor(anchor, 1)):
                if neighbor is None or neighbor in selected_set:
                    continue
                score = _estimate_block_candidate_score(neighbor, selected_set, score_map, pulled_counts)
                neighbor_candidates.append((score, int(neighbor)))
            neighbor_candidates.sort(key=lambda item: (-float(item[0]), int(item[1])))
            for _, neighbor in neighbor_candidates:
                if swap_in([neighbor], {anchor}):
                    iteration_changed = True
                    changed = True
                    break
            if iteration_changed:
                break

        if not iteration_changed:
            break

    ordered = sorted(selected_set, key=lambda n: (-float(score_map.get(n, 0.0)), int(n)))
    return {
        "list": ordered[:target_size],
        "added": sorted(set(added_numbers)),
        "removed": sorted(set(removed_numbers)),
        "changed": changed,
    }


def build_final_suggestion(
    *,
    base_list: List[int],
    optimized_list: List[int],
    optimized_confidence: int,
    optimized_confidence_effective: int | None = None,
    number_details: List[Dict[str, Any]],
    base_confidence_score: int,
    max_size: int,
    history_arr: List[int],
    from_index: int,
    pulled_counts: Dict[int, int],
    base_weight: float,
    optimized_weight: float,
    block_bets_enabled: bool = False,
    inversion_enabled: bool = True,
    inversion_context_window: int = 15,
    inversion_penalty_factor: float = 0.3,
) -> Dict[str, Any]:
    base_numbers = [int(n) for n in base_list if isinstance(n, int)]
    opt_numbers = [int(n) for n in optimized_list if isinstance(n, int)]
    requested_target_size = max(1, min(37, int(max_size)))
    all_numbers = set(base_numbers).union(opt_numbers)
    if not all_numbers:
        return {
            "available": False,
            "list": [],
            "protections": [],
            "invertedNumbers": [],
            "pulledNumbers": [],
            "confidence": {"score": 0, "label": "Baixa"},
            "explanation": "Sem dados suficientes para fusão.",
            "breakdown": {"base_weight": 0.4, "optimized_weight": 0.6, "overlap_ratio": 0, "intersection_bonus": 0},
        }

    pulled_set = {int(n) for n in pulled_counts.keys() if isinstance(n, int)}
    if inversion_enabled and history_arr:
        inversion_analysis = analyze_inversion_context(
            list(all_numbers),
            history_arr,
            from_index,
            window_size=inversion_context_window,
        )
    else:
        inversion_analysis = {"inverted_numbers": set(), "inverted_details": []}

    base_pos = {n: i for i, n in enumerate(base_numbers)}
    opt_pos = {n: i for i, n in enumerate(opt_numbers)}
    details_map = {
        int(item["number"]): item
        for item in number_details
        if isinstance(item, dict) and isinstance(item.get("number"), int)
    }
    base_len = max(1, len(base_numbers))
    opt_len = max(1, len(opt_numbers))
    opt_scores = [float(item.get("net_score", 0.0) or 0.0) for item in details_map.values()]
    min_opt_score = min(opt_scores) if opt_scores else 0.0
    max_opt_score = max(opt_scores) if opt_scores else 1.0
    opt_range = (max_opt_score - min_opt_score) or 1.0
    intersection = {n for n in base_numbers if n in opt_pos}
    inv_set: Set[int] = inversion_analysis["inverted_numbers"]
    effective_optimized_confidence = int(
        optimized_confidence
        if optimized_confidence_effective is None
        else optimized_confidence_effective
    )
    target_size, assertiveness_reasons = _resolve_assertive_target_size(
        requested_target_size=requested_target_size,
        effective_optimized_confidence=effective_optimized_confidence,
        intersection_count=len(intersection),
    )

    ranked: List[Dict[str, Any]] = []
    for n in all_numbers:
        in_base = n in base_pos
        in_opt = n in opt_pos
        base_rank = (1.0 - (base_pos[n] / base_len)) if in_base else 0.0
        opt_rank = (1.0 - (opt_pos[n] / opt_len)) if in_opt else 0.0
        detail = details_map.get(n)
        opt_net = ((float(detail.get("net_score", 0.0) or 0.0) - min_opt_score) / opt_range) if detail else 0.0
        intersection_bonus_item = 0.35 if (n in intersection) else 0.0
        score = (
            (base_weight * base_rank)
            + (optimized_weight * opt_rank)
            + (0.25 * opt_net)
            + intersection_bonus_item
        )

        is_pulled = n in pulled_set
        pull_count = int(pulled_counts.get(n, 0) or 0)
        if is_pulled:
            score += pull_count * 0.5

        is_inverted = (n in inv_set) and (not is_pulled)
        if is_inverted:
            score = score * float(inversion_penalty_factor)

        ranked.append(
            {
                "number": n,
                "score": score,
                "in_base": in_base,
                "in_opt": in_opt,
                "is_inverted": is_inverted,
                "is_pulled": is_pulled,
                "pull_count": pull_count,
            }
        )

    ranked.sort(key=lambda item: (-float(item["score"]), int(item["number"])))
    score_map = {int(item["number"]): float(item["score"]) for item in ranked}
    final_list = [int(item["number"]) for item in ranked[:target_size]]
    block_compaction = {
        "list": list(final_list),
        "added": [],
        "removed": [],
        "changed": False,
    }
    if block_bets_enabled and len(final_list) > 1:
        block_compaction = _compact_final_list_into_blocks(
            initial_list=final_list,
            score_map=dict(score_map),
            pulled_counts=pulled_counts,
            target_size=target_size,
        )
        final_list = [int(n) for n in block_compaction["list"][:target_size]]
    overlap_in_final = len([n for n in final_list if n in intersection])
    overlap_ratio = (overlap_in_final / len(final_list)) if final_list else 0.0
    intersection_bonus = _js_round(overlap_ratio * 12.0)
    merged_raw = (
        (float(effective_optimized_confidence) * optimized_weight)
        + (float(base_confidence_score) * base_weight)
        + float(intersection_bonus)
    )
    merged_score = _js_round(_clamp(merged_raw, 0.0, 100.0))
    base_pct_text = _js_round(base_weight * 100.0)
    opt_pct_text = _js_round(optimized_weight * 100.0)

    protections = find_protections(final_list)
    inverted_in_final = [n for n in final_list if (n in inv_set and n not in pulled_set)]
    inverted_removed = sorted([n for n in inv_set if (n not in final_list and n not in pulled_set)])
    pulled_in_final = [n for n in final_list if n in pulled_set]

    return {
        "available": True,
        "list": final_list,
        "protections": protections,
        "blockBetsEnabled": bool(block_bets_enabled),
        "blockCompaction": block_compaction,
        "invertedNumbers": sorted(inv_set),
        "invertedInFinal": inverted_in_final,
        "invertedRemoved": inverted_removed,
        "pulledNumbers": sorted(pulled_set),
        "pulledInFinal": pulled_in_final,
        "confidence": {
            "score": merged_score,
            "label": confidence_label_from_score(merged_score),
        },
        "explanation": (
            f"Fusão {base_pct_text}/{opt_pct_text} com bônus de interseção ({overlap_in_final}/{len(final_list)})."
            + (
                f" Compactação por assertividade: {requested_target_size}->{target_size}."
                if target_size != requested_target_size
                else ""
            )
            + (
                f" Compactação em blocos aplicada (+{len(block_compaction['added'])}/-{len(block_compaction['removed'])})."
                if bool(block_bets_enabled) and bool(block_compaction["changed"])
                else ""
            )
        ),
        "breakdown": {
            "base_weight": base_weight,
            "optimized_weight": optimized_weight,
            "optimized_confidence_raw": int(optimized_confidence),
            "optimized_confidence_effective": int(effective_optimized_confidence),
            "confidence_source": "optimized_confidence_effective" if optimized_confidence_effective is not None else "optimized_confidence_raw",
            "overlap_ratio": round(overlap_ratio, 3),
            "intersection_bonus": intersection_bonus,
            "requested_target_size": requested_target_size,
            "effective_target_size": target_size,
            "assertiveness_compaction_applied": bool(target_size != requested_target_size),
            "assertiveness_reasons": list(assertiveness_reasons),
            "inversion_penalized": len(inv_set),
            "pulled_bonus": len(pulled_in_final),
            "block_bets_enabled": bool(block_bets_enabled),
            "block_compaction_applied": bool(block_compaction["changed"]),
            "block_numbers_added": len(block_compaction["added"]),
            "block_numbers_removed": len(block_compaction["removed"]),
        },
    }


def build_runtime_overrides(
    *,
    runtime_overrides: Dict[str, Dict[str, Any]] | None,
    siege_window: int,
    siege_min_occurrences: int,
    siege_min_streak: int,
) -> Dict[str, Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    if isinstance(runtime_overrides, dict):
        for key, value in runtime_overrides.items():
            if isinstance(value, dict):
                merged[str(key)] = dict(value)
    siege = dict(merged.get("siege_number_boost", {}))
    siege["window"] = int(siege_window)
    siege["min_occurrences"] = int(siege_min_occurrences)
    siege["min_streak"] = int(siege_min_streak)
    merged["siege_number_boost"] = siege
    return merged

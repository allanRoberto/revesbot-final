#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

try:
    import redis  # type: ignore
except Exception:  # pragma: no cover
    redis = None


MAX_ATTEMPTS_DEFAULT = 4
DEFAULT_WINDOWS = [1, 2, 3, 4, 5, 6, 8, 10]
MIN_BUCKET_SIZE_DEFAULT = 30
CONFIDENCE_RULE_THRESHOLD_CANDIDATES = [60, 70]


@dataclass(frozen=True)
class Strategy:
    code: str
    name: str
    description: str
    decide: Callable[[int, int, float, Optional[int]], Tuple[bool, int]]
    cancel_threshold: Optional[int] = None


@dataclass
class SignalRecord:
    signal_id: str
    status: str
    pattern: str
    roulette_id: str
    bets: List[int]
    trigger: int
    snapshot: List[int]
    history: List[int]
    post_spins: List[int]
    confidence_score: Optional[int]
    confidence_label: Optional[str]
    gales: int


@dataclass
class EvalResult:
    total: int = 0
    entered: int = 0
    wins: int = 0
    losses: int = 0
    cancels: int = 0
    cancels_policy: int = 0
    cancels_paid_waiting: int = 0
    wait_applied: int = 0
    hit1: int = 0
    hit2: int = 0
    hit3: int = 0
    hit4: int = 0
    net_wl: int = 0
    would_win_without_wait: int = 0
    wait_avoided_bad: int = 0
    wait_hurt_win: int = 0

    def as_row(self) -> Dict[str, Any]:
        entered = self.entered
        total = self.total
        return {
            "total_signals": total,
            "entered_signals": entered,
            "coverage": _rate(entered, total),
            "wins": self.wins,
            "losses": self.losses,
            "cancels": self.cancels,
            "win_rate_total": _rate(self.wins, total),
            "loss_rate_total": _rate(self.losses, total),
            "cancel_rate_total": _rate(self.cancels, total),
            "win_rate_entered": _rate(self.wins, entered),
            "loss_rate_entered": _rate(self.losses, entered),
            "hit@1": _rate(self.hit1, entered),
            "hit@2": _rate(self.hit2, entered),
            "hit@3": _rate(self.hit3, entered),
            "hit@4": _rate(self.hit4, entered),
            "net_wl": self.net_wl,
            "paid_waiting_rate_total": _rate(self.cancels_paid_waiting, total),
            "paid_waiting_rate_wait_applied": _rate(self.cancels_paid_waiting, self.wait_applied),
            "would_win_without_wait_rate_wait_applied": _rate(self.would_win_without_wait, self.wait_applied),
            "wait_avoided_bad_rate_paid_waiting": _rate(self.wait_avoided_bad, self.cancels_paid_waiting),
            "wait_hurt_win_rate_wait_applied": _rate(self.wait_hurt_win, self.wait_applied),
        }


@dataclass
class OverlapFeatureSummary:
    total: int = 0
    sum_overlap_unique: int = 0
    sum_overlap_hits: int = 0
    sum_overlap_ratio: float = 0.0

    def add(self, overlap_unique: int, overlap_hits: int, overlap_ratio: float) -> None:
        self.total += 1
        self.sum_overlap_unique += overlap_unique
        self.sum_overlap_hits += overlap_hits
        self.sum_overlap_ratio += overlap_ratio

    def as_row(self) -> Dict[str, Any]:
        if self.total <= 0:
            return {
                "mean_overlap_unique": 0.0,
                "mean_overlap_hits": 0.0,
                "mean_overlap_ratio": 0.0,
            }
        return {
            "mean_overlap_unique": round(self.sum_overlap_unique / self.total, 6),
            "mean_overlap_hits": round(self.sum_overlap_hits / self.total, 6),
            "mean_overlap_ratio": round(self.sum_overlap_ratio / self.total, 6),
        }


def _rate(num: int, den: int) -> float:
    if den <= 0:
        return 0.0
    return round((num / den) * 100.0, 4)


def _safe_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        iv = int(value)
    except Exception:
        return None
    return iv


def _normalize_number_list(values: Any) -> List[int]:
    if not isinstance(values, list):
        return []
    out: List[int] = []
    for raw in values:
        n = _safe_int(raw)
        if n is None:
            continue
        if 0 <= n <= 36:
            out.append(n)
    return out


def _fetch_signals_from_api(signals_url: str, timeout: float) -> List[Dict[str, Any]]:
    req = urllib.request.Request(signals_url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
        payload = resp.read().decode("utf-8")
    data = json.loads(payload)
    if not isinstance(data, list):
        raise ValueError(f"Resposta de {signals_url} não é lista.")
    return [x for x in data if isinstance(x, dict)]


def _fetch_signals_from_redis(redis_url: str) -> List[Dict[str, Any]]:
    if redis is None:
        raise RuntimeError("Pacote redis não disponível para leitura via Redis.")
    client = redis.from_url(redis_url, decode_responses=True)
    rows: List[Dict[str, Any]] = []
    for key in client.scan_iter(match="signal:*", count=5000):
        raw = client.lindex(key, 0)
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _resolve_redis_url(args: argparse.Namespace) -> str:
    if args.redis_url:
        return args.redis_url
    for key in ("REDIS_SIGNALS_CONNECT", "REDIS_CONNECT"):
        val = os.getenv(key)
        if val and val.strip():
            return val.strip()
    return "redis://127.0.0.1:6379/0"


def _load_rows(args: argparse.Namespace) -> Tuple[List[Dict[str, Any]], str]:
    source_mode = args.source.lower().strip()
    errors: List[str] = []

    if source_mode in {"api", "auto"}:
        try:
            rows = _fetch_signals_from_api(args.signals_url, args.http_timeout)
            return rows, f"api:{args.signals_url}"
        except Exception as exc:
            errors.append(f"api falhou: {exc}")
            if source_mode == "api":
                raise

    redis_url = _resolve_redis_url(args)
    try:
        rows = _fetch_signals_from_redis(redis_url)
        return rows, f"redis:{redis_url}"
    except Exception as exc:
        errors.append(f"redis falhou: {exc}")

    raise RuntimeError(" | ".join(errors))


def _build_signal_records(rows: Iterable[Dict[str, Any]], max_attempts: int) -> List[SignalRecord]:
    out: List[SignalRecord] = []
    for row in rows:
        pattern = str(row.get("pattern", ""))
        if pattern != "API_FINAL_SUGGESTION_10":
            continue

        snapshot = _normalize_number_list(row.get("snapshot"))
        history = _normalize_number_list(row.get("history"))
        bets = sorted(set(_normalize_number_list(row.get("bets"))))
        triggers = _normalize_number_list(row.get("triggers"))
        if not snapshot or not bets or not triggers:
            continue

        trigger = triggers[0]
        if trigger != snapshot[0]:
            # Mantém apenas linhas coerentes com o padrão atual.
            continue

        # Reconstrução temporal: history cresce com resultados novos no índice 0.
        # Spins pós-gatilho = prefixo adicional de history em relação a snapshot.
        added = max(0, len(history) - len(snapshot))
        post_spins = list(reversed(history[:added])) if added > 0 else []

        temp_state = row.get("temp_state") if isinstance(row.get("temp_state"), dict) else {}
        confidence_score = _safe_int(temp_state.get("confidence_score")) if isinstance(temp_state, dict) else None
        confidence_label = str(temp_state.get("confidence_label")) if isinstance(temp_state, dict) and temp_state.get("confidence_label") is not None else None

        gales_raw = _safe_int(row.get("gales"))
        gales = max(1, min(max_attempts, gales_raw if gales_raw is not None else max_attempts))

        out.append(
            SignalRecord(
                signal_id=str(row.get("id", "")),
                status=str(row.get("status", "")),
                pattern=pattern,
                roulette_id=str(row.get("roulette_id", "")),
                bets=bets,
                trigger=trigger,
                snapshot=snapshot,
                history=history,
                post_spins=post_spins,
                confidence_score=confidence_score,
                confidence_label=confidence_label,
                gales=gales,
            )
        )
    return out


def _simulate_entry(post_spins: List[int], bets_set: set[int], max_attempts: int) -> Tuple[str, Optional[int]]:
    for idx, number in enumerate(post_spins[:max_attempts], start=1):
        if number in bets_set:
            return "win", idx
    if len(post_spins) >= max_attempts:
        return "loss", None
    return "insufficient", None


def _overlap_features(signal: SignalRecord, lookback_window: int) -> Tuple[int, int, float, List[int]]:
    context = signal.snapshot[1 : 1 + lookback_window]
    if not context:
        return 0, 0, 0.0, []
    bets_set = set(signal.bets)
    overlap_hits = sum(1 for n in context if n in bets_set)
    overlap_unique = len(set(context).intersection(bets_set))
    overlap_ratio = round(overlap_unique / len(signal.bets), 6) if signal.bets else 0.0
    return overlap_unique, overlap_hits, overlap_ratio, context


def _action_no_filter(_u: int, _h: int, _r: float, _c: Optional[int]) -> Tuple[bool, int]:
    return False, 0


def _action_cancel_ge1(u: int, _h: int, _r: float, _c: Optional[int]) -> Tuple[bool, int]:
    return u >= 1, 0


def _action_wait1_ge1(u: int, _h: int, _r: float, _c: Optional[int]) -> Tuple[bool, int]:
    return False, 1 if u >= 1 else 0


def _action_wait2_ge1(u: int, _h: int, _r: float, _c: Optional[int]) -> Tuple[bool, int]:
    return False, 2 if u >= 1 else 0


def _action_wait_proportional(u: int, _h: int, _r: float, _c: Optional[int]) -> Tuple[bool, int]:
    if u <= 0:
        return False, 0
    if u == 1:
        return False, 1
    if u == 2:
        return False, 2
    return False, 3


def _action_cancel_ge_n(n: int) -> Callable[[int, int, float, Optional[int]], Tuple[bool, int]]:
    def _inner(u: int, _h: int, _r: float, _c: Optional[int]) -> Tuple[bool, int]:
        return u >= n, 0

    return _inner


def _build_strategies() -> List[Strategy]:
    return [
        Strategy("A", "Sem Filtro", "Entra sempre (sem filtro).", _action_no_filter),
        Strategy("B", "Cancelar overlap>=1", "Cancela se houver >=1 overlap antes do gatilho.", _action_cancel_ge1, cancel_threshold=1),
        Strategy("C", "Esperar 1 spin", "Espera 1 spin se houver >=1 overlap.", _action_wait1_ge1),
        Strategy("D", "Esperar 2 spins", "Espera 2 spins se houver >=1 overlap.", _action_wait2_ge1),
        Strategy("E", "Espera proporcional", "1 overlap->1, 2 overlaps->2, 3+ overlaps->3.", _action_wait_proportional),
        Strategy("F1", "Cancelar overlap>=1", "Cancela quando overlap>=1.", _action_cancel_ge_n(1), cancel_threshold=1),
        Strategy("F2", "Cancelar overlap>=2", "Cancela quando overlap>=2.", _action_cancel_ge_n(2), cancel_threshold=2),
        Strategy("F3", "Cancelar overlap>=3", "Cancela quando overlap>=3.", _action_cancel_ge_n(3), cancel_threshold=3),
    ]


def _confidence_base_label(score: Optional[int]) -> str:
    if score is None:
        return "unknown"
    if score < 40:
        return "<40"
    if score < 50:
        return "40-49"
    if score < 60:
        return "50-59"
    if score < 70:
        return "60-69"
    return "70+"


def _build_merged_confidence_buckets(scores: List[Optional[int]], min_bucket_size: int) -> List[Tuple[Optional[int], Optional[int], str, int]]:
    # (lower, upper, label, count), com limites inclusivos.
    intervals: List[Tuple[Optional[int], Optional[int], str]] = [
        (None, 39, "<40"),
        (40, 49, "40-49"),
        (50, 59, "50-59"),
        (60, 69, "60-69"),
        (70, None, "70+"),
    ]

    def count_interval(lo: Optional[int], hi: Optional[int]) -> int:
        total = 0
        for s in scores:
            if s is None:
                continue
            if lo is not None and s < lo:
                continue
            if hi is not None and s > hi:
                continue
            total += 1
        return total

    merged: List[Tuple[Optional[int], Optional[int], str, int]] = [
        (lo, hi, label, count_interval(lo, hi)) for lo, hi, label in intervals
    ]

    while len(merged) > 1:
        small = [idx for idx, item in enumerate(merged) if item[3] < min_bucket_size]
        if not small:
            break
        idx = min(small, key=lambda i: merged[i][3])
        if idx == 0:
            join_idx = 1
        elif idx == len(merged) - 1:
            join_idx = idx - 1
        else:
            join_idx = idx - 1 if merged[idx - 1][3] <= merged[idx + 1][3] else idx + 1

        a = merged[min(idx, join_idx)]
        b = merged[max(idx, join_idx)]
        lo = a[0]
        hi = b[1]
        if lo is None and hi is None:
            label = "all"
        elif lo is None:
            label = f"<= {hi}"
        elif hi is None:
            label = f">= {lo}"
        else:
            label = f"{lo}-{hi}"
        count = a[3] + b[3]
        new_item = (lo, hi, label, count)
        merged.pop(max(idx, join_idx))
        merged.pop(min(idx, join_idx))
        merged.insert(min(idx, join_idx), new_item)

    return merged


def _confidence_bucket_label(score: Optional[int], merged: List[Tuple[Optional[int], Optional[int], str, int]]) -> str:
    if score is None:
        return "unknown"
    for lo, hi, label, _count in merged:
        if lo is not None and score < lo:
            continue
        if hi is not None and score > hi:
            continue
        return label
    return "unknown"


def _overlap_group(overlap_unique: int) -> str:
    if overlap_unique <= 0:
        return "0"
    if overlap_unique == 1:
        return "1"
    if overlap_unique == 2:
        return "2"
    return "3+"


def _evaluate_strategies(
    signals: List[SignalRecord],
    strategies: List[Strategy],
    windows: List[int],
    max_attempts: int,
    merged_conf_buckets: List[Tuple[Optional[int], Optional[int], str, int]],
) -> Tuple[
    Dict[Tuple[int, str], EvalResult],
    Dict[Tuple[int, str, str], EvalResult],
    Dict[Tuple[int, str], EvalResult],
    Dict[Tuple[int, str], OverlapFeatureSummary],
    float,
    int,
]:
    overall: Dict[Tuple[int, str], EvalResult] = {}
    by_conf: Dict[Tuple[int, str, str], EvalResult] = {}
    overlap_baseline: Dict[Tuple[int, str], EvalResult] = {}
    overlap_stats: Dict[Tuple[int, str], OverlapFeatureSummary] = {}

    adherence_checks = 0
    adherence_ok = 0

    for signal in signals:
        bets_set = set(signal.bets)
        baseline_outcome, baseline_hit = _simulate_entry(signal.post_spins, bets_set, max_attempts)
        if signal.status in {"win", "lost"} and baseline_outcome in {"win", "loss"}:
            adherence_checks += 1
            if (signal.status == "win" and baseline_outcome == "win") or (
                signal.status == "lost" and baseline_outcome == "loss"
            ):
                adherence_ok += 1

        for window in windows:
            overlap_unique, overlap_hits, overlap_ratio, _ctx = _overlap_features(signal, window)
            conf_bucket = _confidence_bucket_label(signal.confidence_score, merged_conf_buckets)

            # Baseline por grupo de overlap (responde item 2).
            group_key = (window, _overlap_group(overlap_unique))
            grp = overlap_baseline.setdefault(group_key, EvalResult())
            grp.total += 1
            grp_overlap = overlap_stats.setdefault(group_key, OverlapFeatureSummary())
            grp_overlap.add(overlap_unique, overlap_hits, overlap_ratio)
            _accumulate_result(
                grp,
                outcome=baseline_outcome,
                hit_attempt=baseline_hit,
                total_increment=1,
                wait_applied=0,
                canceled_by_policy=False,
                canceled_paid_waiting=False,
                baseline_outcome=baseline_outcome,
            )

            for strategy in strategies:
                cancel_now, wait_spins = strategy.decide(
                    overlap_unique, overlap_hits, overlap_ratio, signal.confidence_score
                )
                key = (window, strategy.code)
                res = overall.setdefault(key, EvalResult())
                res.total += 1

                conf_key = (window, strategy.code, conf_bucket)
                conf_res = by_conf.setdefault(conf_key, EvalResult())
                conf_res.total += 1

                if cancel_now:
                    _accumulate_result(
                        res,
                        outcome="cancelled",
                        hit_attempt=None,
                        total_increment=0,
                        wait_applied=0,
                        canceled_by_policy=True,
                        canceled_paid_waiting=False,
                        baseline_outcome=baseline_outcome,
                    )
                    _accumulate_result(
                        conf_res,
                        outcome="cancelled",
                        hit_attempt=None,
                        total_increment=0,
                        wait_applied=0,
                        canceled_by_policy=True,
                        canceled_paid_waiting=False,
                        baseline_outcome=baseline_outcome,
                    )
                    continue

                wait_spins = max(0, int(wait_spins))
                paid_in_wait = False
                if wait_spins > 0:
                    wait_slice = signal.post_spins[:wait_spins]
                    paid_in_wait = any(n in bets_set for n in wait_slice)

                if wait_spins > 0 and paid_in_wait:
                    _accumulate_result(
                        res,
                        outcome="cancelled",
                        hit_attempt=None,
                        total_increment=0,
                        wait_applied=1,
                        canceled_by_policy=False,
                        canceled_paid_waiting=True,
                        baseline_outcome=baseline_outcome,
                    )
                    _accumulate_result(
                        conf_res,
                        outcome="cancelled",
                        hit_attempt=None,
                        total_increment=0,
                        wait_applied=1,
                        canceled_by_policy=False,
                        canceled_paid_waiting=True,
                        baseline_outcome=baseline_outcome,
                    )
                    continue

                post_after_wait = signal.post_spins[wait_spins:] if wait_spins > 0 else signal.post_spins
                outcome, hit_attempt = _simulate_entry(post_after_wait, bets_set, max_attempts)

                _accumulate_result(
                    res,
                    outcome=outcome,
                    hit_attempt=hit_attempt,
                    total_increment=1,
                    wait_applied=1 if wait_spins > 0 else 0,
                    canceled_by_policy=False,
                    canceled_paid_waiting=False,
                    baseline_outcome=baseline_outcome,
                )
                _accumulate_result(
                    conf_res,
                    outcome=outcome,
                    hit_attempt=hit_attempt,
                    total_increment=1,
                    wait_applied=1 if wait_spins > 0 else 0,
                    canceled_by_policy=False,
                    canceled_paid_waiting=False,
                    baseline_outcome=baseline_outcome,
                )

    adherence = (adherence_ok / adherence_checks) if adherence_checks > 0 else 0.0
    return overall, by_conf, overlap_baseline, overlap_stats, adherence, adherence_checks


def _accumulate_result(
    acc: EvalResult,
    *,
    outcome: str,
    hit_attempt: Optional[int],
    total_increment: int,
    wait_applied: int,
    canceled_by_policy: bool,
    canceled_paid_waiting: bool,
    baseline_outcome: str,
) -> None:
    if total_increment:
        acc.entered += 1
    if wait_applied:
        acc.wait_applied += 1
        if baseline_outcome == "win":
            acc.would_win_without_wait += 1
    if canceled_by_policy:
        acc.cancels += 1
        acc.cancels_policy += 1
        return
    if canceled_paid_waiting:
        acc.cancels += 1
        acc.cancels_paid_waiting += 1
        if baseline_outcome == "loss":
            acc.wait_avoided_bad += 1
        if baseline_outcome == "win":
            acc.wait_hurt_win += 1
        return

    if outcome == "win":
        acc.wins += 1
        acc.net_wl += 1
        if hit_attempt is not None:
            if hit_attempt <= 1:
                acc.hit1 += 1
            if hit_attempt <= 2:
                acc.hit2 += 1
            if hit_attempt <= 3:
                acc.hit3 += 1
            if hit_attempt <= 4:
                acc.hit4 += 1
    elif outcome == "loss":
        acc.losses += 1
        acc.net_wl -= 1
    elif outcome == "cancelled":
        acc.cancels += 1
    else:
        # insufficient
        pass


def _evaluate_rule_mapping(
    signals: List[SignalRecord],
    lookback_window: int,
    max_attempts: int,
    confidence_threshold: int,
    mapping: Dict[Tuple[str, str], str],
) -> EvalResult:
    """
    mapping key: (conf_segment, overlap_group) -> action in {'enter','cancel','wait1','wait2'}
    conf_segment: 'low' | 'high'
    overlap_group: '1' | '2' | '3+'
    overlap_group '0' sempre enter.
    """
    acc = EvalResult(total=0)

    action_to_wait = {"enter": 0, "cancel": -1, "wait1": 1, "wait2": 2}

    for signal in signals:
        acc.total += 1
        bets_set = set(signal.bets)
        baseline_outcome, _baseline_hit = _simulate_entry(signal.post_spins, bets_set, max_attempts)

        overlap_unique, overlap_hits, overlap_ratio, _ctx = _overlap_features(signal, lookback_window)
        _ = overlap_hits, overlap_ratio
        og = _overlap_group(overlap_unique)
        if og == "0":
            action = "enter"
        else:
            seg = "high" if (signal.confidence_score is not None and signal.confidence_score >= confidence_threshold) else "low"
            action = mapping[(seg, og)]

        wait = action_to_wait[action]
        if wait < 0:
            _accumulate_result(
                acc,
                outcome="cancelled",
                hit_attempt=None,
                total_increment=0,
                wait_applied=0,
                canceled_by_policy=True,
                canceled_paid_waiting=False,
                baseline_outcome=baseline_outcome,
            )
            continue

        if wait > 0:
            wait_slice = signal.post_spins[:wait]
            if any(n in bets_set for n in wait_slice):
                _accumulate_result(
                    acc,
                    outcome="cancelled",
                    hit_attempt=None,
                    total_increment=0,
                    wait_applied=1,
                    canceled_by_policy=False,
                    canceled_paid_waiting=True,
                    baseline_outcome=baseline_outcome,
                )
                continue
            post = signal.post_spins[wait:]
            outcome, hit_attempt = _simulate_entry(post, bets_set, max_attempts)
            _accumulate_result(
                acc,
                outcome=outcome,
                hit_attempt=hit_attempt,
                total_increment=1,
                wait_applied=1,
                canceled_by_policy=False,
                canceled_paid_waiting=False,
                baseline_outcome=baseline_outcome,
            )
            continue

        outcome, hit_attempt = _simulate_entry(signal.post_spins, bets_set, max_attempts)
        _accumulate_result(
            acc,
            outcome=outcome,
            hit_attempt=hit_attempt,
            total_increment=1,
            wait_applied=0,
            canceled_by_policy=False,
            canceled_paid_waiting=False,
            baseline_outcome=baseline_outcome,
        )

    return acc


def _best_rule_search(signals: List[SignalRecord], lookback_window: int, max_attempts: int) -> Dict[str, Any]:
    groups = ["1", "2", "3+"]
    actions = ["enter", "cancel", "wait1", "wait2"]

    best: Optional[Tuple[int, float, float, int, Dict[Tuple[str, str], str], EvalResult]] = None
    # score tuple: (net_wl, win_rate_entered, coverage, -cancels)
    for threshold in CONFIDENCE_RULE_THRESHOLD_CANDIDATES:
        all_assignments = list(product(actions, repeat=6))
        for assignment in all_assignments:
            mapping: Dict[Tuple[str, str], str] = {}
            idx = 0
            for seg in ("low", "high"):
                for g in groups:
                    mapping[(seg, g)] = assignment[idx]
                    idx += 1

            result = _evaluate_rule_mapping(
                signals=signals,
                lookback_window=lookback_window,
                max_attempts=max_attempts,
                confidence_threshold=threshold,
                mapping=mapping,
            )
            row = result.as_row()
            coverage = float(row["coverage"])
            win_rate_entered = float(row["win_rate_entered"])
            score = (result.net_wl, win_rate_entered, coverage, -result.cancels)
            if best is None or score > best[:4]:
                best = (score[0], score[1], score[2], score[3], {"threshold": threshold, **{f"{k[0]}_{k[1]}": v for k, v in mapping.items()}}, result)

    if best is None:
        return {}

    return {
        "confidence_threshold": best[4]["threshold"],
        "mapping": {
            "low": {g: best[4][f"low_{g}"] for g in groups},
            "high": {g: best[4][f"high_{g}"] for g in groups},
        },
        "metrics": best[5].as_row(),
    }


def _format_pct(v: float) -> str:
    return f"{v:.2f}%"


def _sort_overall_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(rows, key=lambda r: (r["lookback_window"], r["strategy_code"]))


def _choose_recommended_window(overall_rows: List[Dict[str, Any]]) -> int:
    # escolhe janela com melhor net_wl para estratégias com espera/cancelamento (exclui A/F1 duplicado de B).
    candidates = [
        r
        for r in overall_rows
        if r["strategy_code"] in {"B", "C", "D", "E", "F2", "F3"} and (r["cancel_rate_total"] > 0.0 or r["coverage"] < 100.0)
    ]
    if not candidates:
        candidates = [r for r in overall_rows if r["strategy_code"] in {"B", "C", "D", "E", "F2", "F3"}]
    if not candidates:
        return 4
    best = max(candidates, key=lambda r: (r["net_wl"], r["win_rate_entered"], r["coverage"]))
    return int(best["lookback_window"])


def _build_overlap_feature_rows(
    signals: List[SignalRecord],
    windows: List[int],
    max_attempts: int,
    merged_conf_buckets: List[Tuple[Optional[int], Optional[int], str, int]],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for signal in signals:
        bets_len = len(signal.bets)
        baseline_outcome, baseline_hit = _simulate_entry(signal.post_spins, set(signal.bets), max_attempts)
        conf_bucket = _confidence_bucket_label(signal.confidence_score, merged_conf_buckets)
        for window in windows:
            overlap_unique, overlap_hits, overlap_ratio, _ctx = _overlap_features(signal, window)
            rows.append(
                {
                    "signal_id": signal.signal_id,
                    "roulette_id": signal.roulette_id,
                    "lookback_window": window,
                    "trigger": signal.trigger,
                    "bets_len": bets_len,
                    "overlap_unique": overlap_unique,
                    "overlap_hits": overlap_hits,
                    "overlap_ratio": overlap_ratio,
                    "overlap_group_unique": _overlap_group(overlap_unique),
                    "confidence_score": signal.confidence_score,
                    "confidence_bucket": conf_bucket,
                    "status_observed": signal.status,
                    "baseline_outcome": baseline_outcome,
                    "baseline_hit_attempt": baseline_hit,
                }
            )
    rows.sort(key=lambda r: (r["lookback_window"], str(r["signal_id"])))
    return rows


def _write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    headers = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _make_html_table(rows: List[Dict[str, Any]], title: str, max_rows: int = 120) -> str:
    if not rows:
        return f"<h3>{title}</h3><p>Sem dados.</p>"
    headers = list(rows[0].keys())
    head_html = "".join(f"<th>{h}</th>" for h in headers)
    body_rows = rows[:max_rows]
    body_html = ""
    for row in body_rows:
        body_html += "<tr>" + "".join(f"<td>{row.get(h, '')}</td>" for h in headers) + "</tr>"
    return f"<h3>{title}</h3><table><thead><tr>{head_html}</tr></thead><tbody>{body_html}</tbody></table>"


def _write_html(
    path: Path,
    *,
    generated_at: str,
    source_used: str,
    overall_rows: List[Dict[str, Any]],
    confidence_rows: List[Dict[str, Any]],
    overlap_rows: List[Dict[str, Any]],
) -> None:
    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <title>Overlap Wait Analysis</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 20px; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; font-size: 13px; }}
    th, td {{ border: 1px solid #ddd; padding: 6px 8px; text-align: left; }}
    th {{ background: #f4f4f4; position: sticky; top: 0; }}
    h1, h2, h3 {{ margin: 8px 0; }}
    .meta {{ color: #555; margin-bottom: 14px; }}
  </style>
</head>
<body>
  <h1>Overlap Wait Strategy Analysis</h1>
  <div class="meta">Gerado em {generated_at} | Fonte: {source_used}</div>
  {_make_html_table(overall_rows, "Resumo geral por janela + estratégia")}
  {_make_html_table(confidence_rows, "Estratificação por confidence (janela recomendada)")}
  {_make_html_table(overlap_rows, "Comportamento por overlap (estratégia sem filtro)")}
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Analisa contrafactualmente políticas de entrar/cancelar/esperar "
            "quando há overlap da aposta antes do gatilho."
        )
    )
    parser.add_argument("--source", choices=["auto", "api", "redis"], default="auto")
    parser.add_argument("--signals-url", default=os.getenv("SIGNALS_ENDPOINT", "http://localhost:8000/signals"))
    parser.add_argument("--redis-url", default=None)
    parser.add_argument("--http-timeout", type=float, default=15.0)
    parser.add_argument("--max-attempts", type=int, default=MAX_ATTEMPTS_DEFAULT)
    parser.add_argument("--windows", default="1,2,3,4,5,6,8,10")
    parser.add_argument("--min-bucket-size", type=int, default=MIN_BUCKET_SIZE_DEFAULT)
    parser.add_argument("--out-dir", default="docs")
    args = parser.parse_args()

    windows = []
    for raw in args.windows.split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            n = int(raw)
        except ValueError:
            continue
        if n > 0:
            windows.append(n)
    if not windows:
        windows = list(DEFAULT_WINDOWS)

    rows, source_used = _load_rows(args)
    signals = _build_signal_records(rows, max_attempts=max(1, args.max_attempts))
    if not signals:
        raise RuntimeError("Nenhum sinal válido encontrado para análise.")

    confidence_scores = [s.confidence_score for s in signals]
    merged_conf_buckets = _build_merged_confidence_buckets(confidence_scores, args.min_bucket_size)
    low_mass_original: Dict[str, int] = {}
    base_counts: Dict[str, int] = {}
    for s in signals:
        b = _confidence_base_label(s.confidence_score)
        base_counts[b] = base_counts.get(b, 0) + 1
    for label, count in base_counts.items():
        if label != "unknown" and count < args.min_bucket_size:
            low_mass_original[label] = count

    strategies = _build_strategies()
    overall_map, by_conf_map, overlap_map, overlap_stats, adherence, adherence_checks = _evaluate_strategies(
        signals=signals,
        strategies=strategies,
        windows=windows,
        max_attempts=max(1, args.max_attempts),
        merged_conf_buckets=merged_conf_buckets,
    )

    overall_rows: List[Dict[str, Any]] = []
    for (window, code), eval_result in overall_map.items():
        st = next(s for s in strategies if s.code == code)
        row = {
            "lookback_window": window,
            "strategy_code": st.code,
            "strategy_name": st.name,
            "strategy_desc": st.description,
            **eval_result.as_row(),
        }
        overall_rows.append(row)
    overall_rows = _sort_overall_rows(overall_rows)

    recommended_window = _choose_recommended_window(overall_rows)

    confidence_rows: List[Dict[str, Any]] = []
    for (window, code, conf_bucket), eval_result in by_conf_map.items():
        if window != recommended_window:
            continue
        st = next(s for s in strategies if s.code == code)
        row = {
            "lookback_window": window,
            "strategy_code": st.code,
            "strategy_name": st.name,
            "confidence_bucket": conf_bucket,
            **eval_result.as_row(),
        }
        confidence_rows.append(row)
    confidence_rows.sort(key=lambda r: (r["strategy_code"], r["confidence_bucket"]))

    overlap_rows: List[Dict[str, Any]] = []
    for (window, overlap_group), eval_result in overlap_map.items():
        stats_row = overlap_stats.get((window, overlap_group), OverlapFeatureSummary()).as_row()
        row = {
            "lookback_window": window,
            "strategy_code": "A",
            "strategy_name": "Sem Filtro",
            "overlap_group_unique": overlap_group,
            **stats_row,
            **eval_result.as_row(),
        }
        overlap_rows.append(row)
    overlap_rows.sort(key=lambda r: (r["lookback_window"], r["overlap_group_unique"]))

    overlap_feature_rows = _build_overlap_feature_rows(
        signals=signals,
        windows=windows,
        max_attempts=max(1, args.max_attempts),
        merged_conf_buckets=merged_conf_buckets,
    )

    best_rule = _best_rule_search(
        signals=signals,
        lookback_window=recommended_window,
        max_attempts=max(1, args.max_attempts),
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_overall = out_dir / "overlap-wait-analysis.csv"
    csv_conf = out_dir / "overlap-wait-analysis-confidence.csv"
    csv_overlap = out_dir / "overlap-wait-analysis-overlap.csv"
    csv_features = out_dir / "overlap-wait-analysis-overlap-features.csv"
    md_path = out_dir / "overlap-wait-analysis.md"
    html_path = out_dir / "overlap-wait-analysis.html"

    _write_csv(csv_overall, overall_rows)
    _write_csv(csv_conf, confidence_rows)
    _write_csv(csv_overlap, overlap_rows)
    _write_csv(csv_features, overlap_feature_rows)

    generated_at = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %z")

    merged_bucket_lines = []
    for lo, hi, label, count in merged_conf_buckets:
        merged_bucket_lines.append(f"- `{label}`: {count} sinais")

    low_mass_lines = []
    if low_mass_original:
        for label, count in sorted(low_mass_original.items()):
            low_mass_lines.append(f"- bucket original `{label}` tem baixa massa (`n={count}`), tratado por merge para análise.")
    else:
        low_mass_lines.append("- nenhum bucket original abaixo do mínimo configurado.")

    top_overall = sorted(
        [
            r
            for r in overall_rows
            if r["strategy_code"] in {"B", "C", "D", "E", "F2", "F3"}
            and (r["cancel_rate_total"] > 0.0 or r["coverage"] < 100.0)
        ],
        key=lambda r: (r["net_wl"], r["win_rate_entered"], r["coverage"]),
        reverse=True,
    )[:8]

    top_lines = []
    for row in top_overall:
        top_lines.append(
            f"- janela `{row['lookback_window']}` | {row['strategy_code']} `{row['strategy_name']}` | "
            f"coverage `{_format_pct(row['coverage'])}` | win_rate_entered `{_format_pct(row['win_rate_entered'])}` | "
            f"cancel_rate `{_format_pct(row['cancel_rate_total'])}` | net_wl `{row['net_wl']}`"
        )

    rule_lines = []
    if best_rule:
        thr = best_rule["confidence_threshold"]
        m_low = best_rule["mapping"]["low"]
        m_high = best_rule["mapping"]["high"]
        met = best_rule["metrics"]
        rule_lines.extend(
            [
                f"- confidence de corte: `>= {thr}` = alta, `< {thr}` = baixa/média",
                f"- overlap `1` -> baixa/média: `{m_low['1']}` | alta: `{m_high['1']}`",
                f"- overlap `2` -> baixa/média: `{m_low['2']}` | alta: `{m_high['2']}`",
                f"- overlap `3+` -> baixa/média: `{m_low['3+']}` | alta: `{m_high['3+']}`",
                "- overlap `0` -> `enter` (sempre)",
                (
                    f"- métricas da regra buscada (janela {recommended_window}): "
                    f"coverage `{_format_pct(met['coverage'])}`, "
                    f"win_rate_entered `{_format_pct(met['win_rate_entered'])}`, "
                    f"cancel_rate `{_format_pct(met['cancel_rate_total'])}`, "
                    f"net_wl `{met['net_wl']}`"
                ),
            ]
        )
    else:
        rule_lines.append("- regra ótima não pôde ser calculada.")

    md = f"""# Overlap Wait Analysis

## Escopo
Análise focada em decisão de estratégia (entrar, cancelar, esperar), sem refatoração estrutural.

## Fonte e Dataset
- fonte utilizada: `{source_used}`
- sinais lidos: `{len(rows)}`
- sinais válidos para o padrão `API_FINAL_SUGGESTION_10`: `{len(signals)}`
- tentativas simuladas: até `{max(1, args.max_attempts)}`
- janelas testadas: `{", ".join(map(str, windows))}`

## Aviso Metodológico (Contrafactual)
Esta análise de esperar/cancelar é **contrafactual** e baseada em **reconstrução do histórico** (`snapshot` + `history`).
Nos casos observados com status real `win/lost`, a reconstrução reproduziu o desfecho em aproximadamente:
- aderência: `{adherence*100:.2f}%`
- base de validação: `{adherence_checks}` sinais

## Schema Real Utilizado de /signals
- `triggers[0]`: gatilho (100%)
- `bets`: números da aposta (100%)
- `snapshot`: histórico da formação do padrão (100%)
- `history`: histórico ampliado pós-emissão (100%)
- `gales`, `attempts`, `status` (100%)
- `temp_state.confidence_score`, `temp_state.confidence_label` (100%)
- `spins_required`: presença histórica baixa (quase nula no legado)
- `paid_waiting`: ausente no legado histórico atual

## Campos Úteis para Reconstrução
- gatilho: `triggers[0]` e validação com `snapshot[0]`
- aposta: `bets`
- contexto anterior ao gatilho: `snapshot[1:1+lookback]`
- tentativas máximas: `gales` (cap em 4 para simulação)
- confidence: `temp_state.confidence_score` e `temp_state.confidence_label`
- desfecho observado: `status`
- desfecho reconstruído: primeiros spins pós-gatilho inferidos de `history` vs `snapshot`

## Limitações do Dataset
- `paid_waiting` não existe historicamente no legado atual, então taxa de "pagou na espera" é inferida contrafactualmente.
- `spins_required` quase não aparece no histórico legado.
- parte das perguntas de espera/cancelamento depende de simulação de política (não de observação direta em produção).

## Perguntas Diretas vs Inferência
Perguntas respondidas diretamente pelos dados observados:
- distribuição de confidence
- frequência de overlap por janela
- desempenho observado do fluxo sem política contrafactual adicional

Perguntas que exigem inferência/reconstrução:
- "esperar melhora ou piora" vs "cancelar" (comparativo contrafactual)
- "pagou na espera"
- "teria ganho se não esperasse"
- "espera evitou entrada ruim"

## Variáveis de Overlap
Para cada janela de lookback:
- `overlap_unique = |set(bets) ∩ set(contexto_pre_gatilho)|`
- `overlap_hits = contagem de ocorrências de números de bets no contexto`
- `overlap_ratio = overlap_unique / len(bets)`
- registro detalhado por sinal/janela em: `{csv_features}`

## Buckets de Confidence
Buckets originais avaliados: `<40`, `40-49`, `50-59`, `60-69`, `70+`.
Tratamento de baixa massa:
{chr(10).join(low_mass_lines)}

Buckets efetivos usados na análise:
{chr(10).join(merged_bucket_lines)}

## Estratégias Comparadas
- A: sem filtro (entra direto)
- B: cancela com `overlap >= 1`
- C: espera 1 spin com `overlap >= 1` (se pagar na espera, cancela)
- D: espera 2 spins com `overlap >= 1` (se pagar na espera, cancela)
- E: espera proporcional (`1->1`, `2->2`, `3+->3`)
- F1/F2/F3: cancela com `overlap >= N` (`N=1,2,3`)

## Top Resultados (geral)
{chr(10).join(top_lines) if top_lines else "- sem resultados"}

## Recomendação Prática (Regra)
Janela recomendada para olhar para trás:
- **`{recommended_window}` casas**

Regra proposta por overlap e confidence:
{chr(10).join(rule_lines)}

## Resposta Objetiva da Etapa
- Com os dados históricos disponíveis, é possível comparar entrar vs cancelar vs esperar.
- O efeito de confidence foi estratificado com merge de buckets de baixa massa.
- A recomendação acima já traduz o resultado em política operacional por `overlap (1/2/3+)` e confidence.

## Arquivos Gerados
- CSV geral: `{csv_overall}`
- CSV confidence: `{csv_conf}`
- CSV overlap: `{csv_overlap}`
- CSV features overlap: `{csv_features}`
- HTML: `{html_path}`
"""
    md_path.write_text(md, encoding="utf-8")

    _write_html(
        html_path,
        generated_at=generated_at,
        source_used=source_used,
        overall_rows=overall_rows,
        confidence_rows=confidence_rows,
        overlap_rows=overlap_rows,
    )

    print(f"OK: {len(signals)} sinais analisados")
    print(f"Fonte: {source_used}")
    print(f"Aderência reconstrução win/lost: {adherence*100:.2f}% (n={adherence_checks})")
    print(f"Janela recomendada: {recommended_window}")
    if best_rule:
        print(f"Regra confiança (threshold={best_rule['confidence_threshold']}): {best_rule['mapping']}")
        print(f"Métricas regra: {best_rule['metrics']}")
    print(f"Relatório: {md_path}")
    print(f"HTML: {html_path}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Interrompido.", file=sys.stderr)
        raise

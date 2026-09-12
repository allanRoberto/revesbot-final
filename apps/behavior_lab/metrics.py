from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from .contracts import Signal, SignalStatus


DISTANCE_BUCKETS: tuple[tuple[str, int, int | None], ...] = (
    ("0-10", 0, 10),
    ("11-50", 11, 50),
    ("51-100", 51, 100),
    ("101-150", 101, 150),
    ("151-200", 151, 200),
    ("201-300", 201, 300),
    ("301-400", 301, 400),
    ("401-499", 401, 499),
    ("500+", 500, None),
)


def _signal_distance(signal: Signal) -> int | None:
    evidence = signal.evidence if isinstance(signal.evidence, Mapping) else {}
    try:
        prior = int(evidence["prior_start_index"])
        current = int(evidence["current_start_index"])
    except (KeyError, TypeError, ValueError):
        return None
    distance = current - prior
    return distance if distance >= 0 else None


def _distance_bucket(distance: int) -> str:
    for label, minimum, maximum in DISTANCE_BUCKETS:
        if distance >= minimum and (maximum is None or distance <= maximum):
            return label
    return "500+"


def _empty_distance_row() -> dict[str, int]:
    return {"resolved": 0, "won": 0, "lost": 0}


def archive_signals(
    archive: Mapping[str, Any] | None,
    signals: Sequence[Signal],
) -> dict[str, Any]:
    """Fold immutable resolved signals into a compact lifetime accumulator."""

    result: dict[str, Any] = {
        "activated": int((archive or {}).get("activated", 0)),
        "statuses": dict((archive or {}).get("statuses", {})),
        "payment_types": dict((archive or {}).get("payment_types", {})),
        "wins_by_attempt": dict((archive or {}).get("wins_by_attempt", {})),
        "by_rule": {
            str(rule): dict(row)
            for rule, row in dict((archive or {}).get("by_rule", {})).items()
        },
        "distance_by_rule": {
            str(rule): {
                str(bucket): {
                    "resolved": int(dict(row).get("resolved", 0)),
                    "won": int(dict(row).get("won", 0)),
                    "lost": int(dict(row).get("lost", 0)),
                }
                for bucket, row in dict(buckets).items()
            }
            for rule, buckets in dict((archive or {}).get("distance_by_rule", {})).items()
        },
        "random_expected_wins_same_coverage_horizon": float(
            (archive or {}).get("random_expected_wins_same_coverage_horizon", 0.0)
        ),
    }
    for signal in signals:
        if signal.status == SignalStatus.ACTIVE:
            raise ValueError("sinal ativo nao pode ser arquivado")
        status = signal.status.value
        result["activated"] += 1
        result["statuses"][status] = int(result["statuses"].get(status, 0)) + 1
        if signal.status == SignalStatus.WON:
            payment_type = str(signal.payment_type)
            result["payment_types"][payment_type] = (
                int(result["payment_types"].get(payment_type, 0)) + 1
            )
            attempt = str(signal.attempts)
            result["wins_by_attempt"][attempt] = (
                int(result["wins_by_attempt"].get(attempt, 0)) + 1
            )
        if signal.status in (SignalStatus.WON, SignalStatus.LOST):
            coverage = len(set(signal.suggested_numbers)) / 37.0
            result["random_expected_wins_same_coverage_horizon"] += (
                1.0 - (1.0 - coverage) ** 10
            )
        rule_row = result["by_rule"].setdefault(
            signal.rule,
            {"activated": 0, "active": 0, "won": 0, "lost": 0, "censored": 0},
        )
        rule_row["activated"] = int(rule_row.get("activated", 0)) + 1
        rule_row[status] = int(rule_row.get(status, 0)) + 1
        if signal.status in (SignalStatus.WON, SignalStatus.LOST):
            distance = _signal_distance(signal)
            if distance is not None:
                bucket = _distance_bucket(distance)
                distance_row = result["distance_by_rule"].setdefault(
                    signal.rule, {}
                ).setdefault(bucket, _empty_distance_row())
                distance_row["resolved"] += 1
                distance_row[status] += 1
    return result


def _rate(numerator: int | float, denominator: int | float) -> float | None:
    if not denominator:
        return None
    return round(float(numerator) / float(denominator), 6)


def _max_drawdown(profits: Sequence[float]) -> float:
    equity = 0.0
    peak = 0.0
    maximum = 0.0
    for profit in profits:
        equity += profit
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)
    return round(maximum, 6)


def _max_loss_streak(decisions: Sequence[Mapping[str, Any]]) -> int:
    current = 0
    maximum = 0
    for decision in decisions:
        if decision["hit"]:
            current = 0
        else:
            current += 1
            maximum = max(maximum, current)
    return maximum


def build_metrics(
    *,
    signals: Sequence[Signal],
    decisions: Sequence[Mapping[str, Any]],
    accepted_spins: int,
    duplicate_events: int,
    archived_signals: Mapping[str, Any] | None = None,
    decisions_scope: str = "retained_window",
) -> dict[str, Any]:
    archived = archived_signals or {}
    statuses = Counter(
        {str(key): int(value) for key, value in dict(archived.get("statuses", {})).items()}
    )
    statuses.update(signal.status.value for signal in signals)
    resolved = statuses[SignalStatus.WON.value] + statuses[SignalStatus.LOST.value]
    completed_signals = [
        signal
        for signal in signals
        if signal.status in (SignalStatus.WON, SignalStatus.LOST)
    ]
    expected_random_signal_wins = float(
        archived.get("random_expected_wins_same_coverage_horizon", 0.0)
    ) + sum(
        1.0 - (1.0 - (len(set(signal.suggested_numbers)) / 37.0)) ** 10
        for signal in completed_signals
    )
    payment_types = Counter(
        {
            str(key): int(value)
            for key, value in dict(archived.get("payment_types", {})).items()
        }
    )
    payment_types.update(
        signal.payment_type for signal in signals if signal.status == SignalStatus.WON
    )
    attempts = Counter(
        {
            int(key): int(value)
            for key, value in dict(archived.get("wins_by_attempt", {})).items()
        }
    )
    attempts.update(
        signal.attempts for signal in signals if signal.status == SignalStatus.WON
    )

    rule_rows: dict[str, dict[str, int]] = defaultdict(
        lambda: {"activated": 0, "active": 0, "won": 0, "lost": 0, "censored": 0}
    )
    for rule, archived_row in dict(archived.get("by_rule", {})).items():
        row = rule_rows[str(rule)]
        for key in row:
            row[key] = int(dict(archived_row).get(key, 0))
    for signal in signals:
        row = rule_rows[signal.rule]
        row["activated"] += 1
        row[signal.status.value] += 1

    distance_rows: dict[str, dict[str, dict[str, int]]] = defaultdict(dict)
    for rule, buckets in dict(archived.get("distance_by_rule", {})).items():
        for bucket, archived_row in dict(buckets).items():
            distance_rows[str(rule)][str(bucket)] = {
                key: int(dict(archived_row).get(key, 0))
                for key in ("resolved", "won", "lost")
            }
    for signal in completed_signals:
        distance = _signal_distance(signal)
        if distance is None:
            continue
        bucket = _distance_bucket(distance)
        row = distance_rows[signal.rule].setdefault(bucket, _empty_distance_row())
        row["resolved"] += 1
        row[signal.status.value] += 1

    distance_metrics: dict[str, Any] = {}
    distance_available = 0
    for rule, rule_row in sorted(rule_rows.items()):
        buckets = distance_rows.get(rule, {})
        available = sum(row["resolved"] for row in buckets.values())
        resolved_for_rule = rule_row["won"] + rule_row["lost"]
        distance_available += available
        distance_metrics[rule] = {
            "resolved": resolved_for_rule,
            "with_distance": available,
            "distance_unavailable": max(0, resolved_for_rule - available),
            "buckets": {
                label: {
                    **buckets.get(label, _empty_distance_row()),
                    "win_rate": _rate(
                        buckets.get(label, {}).get("won", 0),
                        buckets.get(label, {}).get("resolved", 0),
                    ),
                }
                for label, _, _ in DISTANCE_BUCKETS
            },
        }

    rule_metrics: dict[str, dict[str, Any]] = {}
    for rule, row in sorted(rule_rows.items()):
        denominator = row["won"] + row["lost"]
        rule_metrics[rule] = {
            **row,
            "win_rate": _rate(row["won"], denominator),
        }

    bet_decisions = [decision for decision in decisions if decision["suggestion"]]
    prediction_hits = sum(bool(decision["hit"]) for decision in bet_decisions)
    total_numbers_staked = sum(len(decision["suggestion"]) for decision in bet_decisions)
    expected_random_hits = sum(len(decision["suggestion"]) / 37.0 for decision in bet_decisions)
    profits = [
        float(36 - len(decision["suggestion"]))
        if decision["hit"]
        else float(-len(decision["suggestion"]))
        for decision in bet_decisions
    ]
    profit = round(sum(profits), 6)

    return {
        "spins": {
            "accepted": accepted_spins,
            "duplicate_events_ignored": duplicate_events,
        },
        "signals": {
            "scope": "lifetime",
            "activated": int(archived.get("activated", 0)) + len(signals),
            "retained_records": len(signals),
            "archived_records": int(archived.get("activated", 0)),
            "active": statuses[SignalStatus.ACTIVE.value],
            "won": statuses[SignalStatus.WON.value],
            "lost": statuses[SignalStatus.LOST.value],
            "censored": statuses[SignalStatus.CENSORED.value],
            "resolved": resolved,
            "win_rate": _rate(statuses[SignalStatus.WON.value], resolved),
            "random_expected_wins_same_coverage_horizon": round(
                expected_random_signal_wins, 6
            ),
            "random_expected_win_rate_same_coverage_horizon": _rate(
                expected_random_signal_wins, resolved
            ),
            "payment_types": {
                "exact": payment_types["exact"],
                "neighbor": payment_types["neighbor"],
                "mirror": payment_types["mirror"],
            },
            "wins_by_attempt": {
                str(attempt): attempts[attempt]
                for attempt in range(1, 11)
            },
            "by_rule": rule_metrics,
            "distance_analysis": {
                "resolved": resolved,
                "with_distance": distance_available,
                "distance_unavailable": max(0, resolved - distance_available),
                "by_rule": distance_metrics,
            },
        },
        "decisions": {
            "scope": decisions_scope,
            "window_spins": len(decisions),
            "total": len(decisions),
            "bets": len(bet_decisions),
            "abstentions": len(decisions) - len(bet_decisions),
            "abstention_rate": _rate(len(decisions) - len(bet_decisions), len(decisions)),
            "hits": prediction_hits,
            "hit_rate": _rate(prediction_hits, len(bet_decisions)),
            "average_group_size": _rate(total_numbers_staked, len(bet_decisions)),
            "random_expected_hits_same_coverage": round(expected_random_hits, 6),
            "random_expected_hit_rate_same_coverage": _rate(expected_random_hits, len(bet_decisions)),
        },
        "flat_stake": {
            "units_staked": total_numbers_staked,
            "net_units": profit,
            "roi": _rate(profit, total_numbers_staked),
            "max_drawdown_units": _max_drawdown(profits),
            "max_loss_streak": _max_loss_streak(bet_decisions),
            "assumption": "one unit per suggested straight number; European payout 35:1",
        },
    }

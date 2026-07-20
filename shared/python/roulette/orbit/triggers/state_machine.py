"""Funcoes puras para construir e acompanhar entradas de gatilho."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from ..constants import EUROPEAN_WHEEL, WHEEL_INDEX, validate_number
from .catalog import DEFAULT_MAX_ATTEMPTS


@dataclass(frozen=True, slots=True)
class TriggerActivation:
    strategy_slug: str
    entry_numbers: tuple[int, ...]
    base_numbers: tuple[int, ...]
    source_trial_id: str
    metadata: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class CandidateTransition:
    update: Mapping[str, Any]
    activation: TriggerActivation | None = None


def wheel_neighbors(number: int, *, span: int, include_center: bool = True) -> tuple[int, ...]:
    safe_number = validate_number(number)
    safe_span = max(0, min(18, int(span)))
    index = WHEEL_INDEX[safe_number]
    offsets = range(-safe_span, safe_span + 1)
    values = [
        EUROPEAN_WHEEL[(index + offset) % len(EUROPEAN_WHEEL)]
        for offset in offsets
        if include_center or offset != 0
    ]
    return tuple(dict.fromkeys(values))


def expand_with_neighbors(numbers: Sequence[int], *, span: int) -> tuple[int, ...]:
    expanded: list[int] = []
    for number in numbers:
        expanded.extend(wheel_neighbors(number, span=span, include_center=True))
    return tuple(dict.fromkeys(expanded))


def terminal_members(number: int) -> tuple[int, ...]:
    terminal = validate_number(number) % 10
    return tuple(value for value in range(37) if value % 10 == terminal)


def build_ryan_entry(
    recent_pivots: Sequence[int],
    suggestion: Sequence[int],
    *,
    candidate_limit: int = 4,
) -> dict[str, tuple[int, ...]] | None:
    pivots = tuple(validate_number(value) for value in recent_pivots[:3])
    top9 = tuple(dict.fromkeys(validate_number(value) for value in suggestion[:9]))
    if len(pivots) != 3 or len(top9) < 1:
        return None
    confluence_positions = [index for index, value in enumerate(pivots) if value in top9]
    if len(confluence_positions) != 1:
        return None

    remaining = tuple(
        value for index, value in enumerate(pivots) if index != confluence_positions[0]
    )
    pivot_neighbors: list[int] = []
    for pivot in remaining:
        pivot_neighbors.extend(wheel_neighbors(pivot, span=1, include_center=False))
    pivot_neighbors = list(dict.fromkeys(pivot_neighbors))

    terminal_pool: set[int] = set()
    for neighbor in pivot_neighbors:
        terminal_pool.update(terminal_members(neighbor))
    base_numbers = tuple(number for number in top9 if number in terminal_pool)
    if not 1 <= len(base_numbers) <= max(1, int(candidate_limit)):
        return None
    entry_numbers = expand_with_neighbors(base_numbers, span=2)
    return {
        "confluence": (pivots[confluence_positions[0]],),
        "remaining_pivots": remaining,
        "pivot_neighbors": tuple(pivot_neighbors),
        "base_numbers": base_numbers,
        "entry_numbers": entry_numbers,
    }


def advance_trigger_trial_document(
    trial: Mapping[str, Any],
    *,
    number: int,
    history_id: str,
    timestamp: Any,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> dict[str, Any] | None:
    existing_ids = [str(value) for value in trial.get("attempt_history_ids") or []]
    if str(history_id) in existing_ids:
        return None
    attempts = [int(value) for value in trial.get("attempt_numbers") or []]
    safe_attempts = max(1, int(max_attempts))
    if len(attempts) >= safe_attempts:
        return None

    safe_number = validate_number(number)
    attempts.append(safe_number)
    existing_ids.append(str(history_id))
    timestamps = list(trial.get("attempt_timestamps_utc") or [])
    timestamps.append(timestamp)
    first_hit = trial.get("first_hit_attempt")
    if first_hit is None and safe_number in set(trial.get("entry_numbers") or []):
        first_hit = len(attempts)
    resolved = len(attempts) >= safe_attempts
    payload: dict[str, Any] = {
        "attempt_numbers": attempts,
        "attempt_history_ids": existing_ids,
        "attempt_timestamps_utc": timestamps,
        "attempts_observed": len(attempts),
        "first_hit_attempt": first_hit,
        "status": "resolved" if resolved else "pending",
        "updated_at_utc": datetime.now(timezone.utc),
    }
    if resolved:
        payload["resolved_at_utc"] = timestamp
    return payload


def _activation(
    candidate: Mapping[str, Any],
    *,
    entry_numbers: Sequence[int],
    base_numbers: Sequence[int],
    metadata: Mapping[str, Any] | None = None,
) -> TriggerActivation:
    return TriggerActivation(
        strategy_slug=str(candidate["strategy_slug"]),
        entry_numbers=tuple(dict.fromkeys(validate_number(value) for value in entry_numbers)),
        base_numbers=tuple(dict.fromkeys(validate_number(value) for value in base_numbers)),
        source_trial_id=str(candidate.get("source_trial_id") or ""),
        metadata=dict(metadata or {}),
    )


def advance_candidate(
    candidate: Mapping[str, Any],
    *,
    number: int,
    current_prediction: Mapping[str, Any],
) -> CandidateTransition:
    """Avanca um candidato exatamente uma vez para o novo giro."""

    strategy = str(candidate.get("strategy_slug") or "")
    safe_number = validate_number(number)
    observed = int(candidate.get("observed_spins") or 0) + 1
    source_top9 = tuple(int(value) for value in candidate.get("source_top9") or [])
    now = datetime.now(timezone.utc)

    if strategy == "green-primeira":
        remaining = max(0, int(candidate.get("wait_remaining") or 0) - 1)
        if remaining == 0:
            current_top9 = tuple(int(value) for value in current_prediction.get("top9") or [])[:9]
            return CandidateTransition(
                update={"status": "activated", "observed_spins": observed, "updated_at_utc": now},
                activation=_activation(
                    candidate,
                    entry_numbers=current_top9,
                    base_numbers=current_top9,
                    metadata={"waited_spins": observed},
                ),
            )
        return CandidateTransition(
            update={"wait_remaining": remaining, "observed_spins": observed, "updated_at_utc": now}
        )

    if strategy in {"inception", "inception-primeiros-4"}:
        watched = source_top9 if strategy == "inception" else source_top9[:4]
        if safe_number in watched:
            return CandidateTransition(
                update={
                    "status": "cancelled_hit",
                    "observed_spins": observed,
                    "cancelled_number": safe_number,
                    "updated_at_utc": now,
                }
            )
        if observed >= 6:
            entry = watched if strategy == "inception" else expand_with_neighbors(watched, span=1)
            return CandidateTransition(
                update={"status": "activated", "observed_spins": observed, "updated_at_utc": now},
                activation=_activation(
                    candidate,
                    entry_numbers=entry,
                    base_numbers=watched,
                    metadata={"absence_spins": observed},
                ),
            )
        return CandidateTransition(
            update={"observed_spins": observed, "updated_at_utc": now}
        )

    if strategy == "interrompimento":
        phase = str(candidate.get("phase") or "learning")
        gap = int(candidate.get("gap") or 0)
        rhythm_hits = int(candidate.get("rhythm_hits") or 0)
        matched = safe_number in source_top9
        if phase == "learning":
            if matched:
                rhythm_hits += 1
                gap = 0
                phase = "qualified" if rhythm_hits >= 3 else "learning"
            else:
                gap += 1
                if gap > 4:
                    return CandidateTransition(
                        update={
                            "status": "cancelled_broken_rhythm",
                            "observed_spins": observed,
                            "gap": gap,
                            "rhythm_hits": rhythm_hits,
                            "updated_at_utc": now,
                        }
                    )
        else:
            gap = 0 if matched else gap + 1
            if gap >= 5:
                current_top9 = tuple(int(value) for value in current_prediction.get("top9") or [])[:9]
                return CandidateTransition(
                    update={
                        "status": "activated",
                        "observed_spins": observed,
                        "gap": gap,
                        "rhythm_hits": rhythm_hits,
                        "updated_at_utc": now,
                    },
                    activation=_activation(
                        candidate,
                        entry_numbers=current_top9,
                        base_numbers=current_top9,
                        metadata={"rhythm_hits": rhythm_hits, "interruption_gap": gap},
                    ),
                )
        if observed >= 180:
            return CandidateTransition(
                update={"status": "expired", "observed_spins": observed, "updated_at_utc": now}
            )
        return CandidateTransition(
            update={
                "phase": phase,
                "gap": gap,
                "rhythm_hits": rhythm_hits,
                "observed_spins": observed,
                "updated_at_utc": now,
            }
        )

    if strategy == "distancia":
        phase = str(candidate.get("phase") or "observing")
        if phase == "waiting":
            remaining = max(0, int(candidate.get("wait_remaining") or 0) - 1)
            if remaining == 0:
                return CandidateTransition(
                    update={"status": "activated", "observed_spins": observed, "updated_at_utc": now},
                    activation=_activation(
                        candidate,
                        entry_numbers=source_top9,
                        base_numbers=source_top9,
                        metadata={"hit_distance": int(candidate.get("hit_distance") or 0)},
                    ),
                )
            return CandidateTransition(
                update={
                    "wait_remaining": remaining,
                    "observed_spins": observed,
                    "updated_at_utc": now,
                }
            )
        if safe_number in source_top9:
            hit_distance = observed
            remaining = hit_distance - 1
            if remaining == 0:
                return CandidateTransition(
                    update={
                        "status": "activated",
                        "observed_spins": observed,
                        "hit_distance": hit_distance,
                        "updated_at_utc": now,
                    },
                    activation=_activation(
                        candidate,
                        entry_numbers=source_top9,
                        base_numbers=source_top9,
                        metadata={"hit_distance": hit_distance},
                    ),
                )
            return CandidateTransition(
                update={
                    "phase": "waiting",
                    "hit_distance": hit_distance,
                    "wait_remaining": remaining,
                    "observed_spins": observed,
                    "updated_at_utc": now,
                }
            )
        if observed >= 36:
            return CandidateTransition(
                update={"status": "expired_no_hit", "observed_spins": observed, "updated_at_utc": now}
            )
        return CandidateTransition(update={"observed_spins": observed, "updated_at_utc": now})

    raise ValueError(f"candidato com estrategia nao suportada: {strategy}")

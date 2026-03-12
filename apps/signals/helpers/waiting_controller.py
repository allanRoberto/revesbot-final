from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set


@dataclass
class _WaitingEntry:
    signal: Dict[str, Any]
    triggers: Set[int]


class WaitingController:
    def __init__(self) -> None:
        self._waiting: Dict[str, _WaitingEntry] = {}

    def register(self, signal: Dict[str, Any]) -> None:
        triggers = _normalize_int_list(signal.get("triggers"))
        if not triggers:
            return
        key = _build_key(signal, triggers)
        self._waiting[key] = _WaitingEntry(signal=signal, triggers=set(triggers))

    def consume_trigger(self, last_number: Optional[int]) -> List[Dict[str, Any]]:
        if last_number is None:
            return []
        fired: List[Dict[str, Any]] = []
        for key, entry in list(self._waiting.items()):
            if last_number in entry.triggers:
                promoted = dict(entry.signal)
                promoted["status"] = "processing"
                fired.append(promoted)
                del self._waiting[key]
        return fired


waiting_controller = WaitingController()


def _normalize_int_list(value: Any) -> List[int]:
    if value is None:
        return []
    if isinstance(value, list):
        return [int(v) for v in value]
    return [int(value)]


def _build_key(signal: Dict[str, Any], triggers: Iterable[int]) -> str:
    roulette_id = signal.get("roulette_id") or signal.get("roulette_slug") or signal.get("roulette_name")
    pattern = signal.get("pattern") or ""
    trigger_key = ",".join(str(t) for t in sorted(set(triggers)))
    targets = signal.get("targets")
    if isinstance(targets, list):
        target_key = ",".join(str(t) for t in sorted(set(targets)))
    elif targets is None:
        target_key = ""
    else:
        target_key = str(targets)
    return f"{roulette_id}|{pattern}|{trigger_key}|{target_key}"

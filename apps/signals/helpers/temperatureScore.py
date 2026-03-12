from dataclasses import dataclass, asdict
from typing import Iterable, Optional, Dict, Any
import time

def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

@dataclass
class TemperatureState:
    value: float = 50.0
    last_event_id: Optional[str] = None
    updated_at: float = 0.0  # epoch seconds

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "TemperatureState":
        return TemperatureState(
            value=float(d.get("value", 50.0)),
            last_event_id=d.get("last_event_id"),
            updated_at=float(d.get("updated_at", 0.0)),
        )

@dataclass
class TemperatureEvent:
    event_id: str
    tags: Iterable[str]
    gale_hit: Optional[int] = None
    waited_spins: Optional[int] = None
    meta: Optional[Dict[str, Any]] = None


class TemperatureUpdater:
    def __init__(self, tag_weights: Dict[str, float], alpha: float = 0.2):
        self.tag_weights = tag_weights
        self.alpha = alpha

    def apply(self, state: TemperatureState, ev: TemperatureEvent) -> TemperatureState:
        # idempotência: não aplica duas vezes o mesmo evento
        if state.last_event_id == ev.event_id:
            return state

        delta = 0.0
        for t in ev.tags:
            delta += self.tag_weights.get(t, 0.0)

        if ev.gale_hit is not None:
            delta += 3.0 * ev.gale_hit

        if ev.waited_spins is not None:
            delta += 1.5 * ev.waited_spins

        raw = clamp(state.value + delta, 0.0, 100.0)
        new_value = (1 - self.alpha) * state.value + self.alpha * raw

        return TemperatureState(
            value=new_value,
            last_event_id=ev.event_id,
            updated_at=time.time(),
        )
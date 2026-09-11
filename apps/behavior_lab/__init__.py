"""Independent, causal roulette behaviour replay engine.

The package deliberately does not import any of the repository's existing
signal, pattern, monitoring, or collector implementations.  Its only external
inputs are result events.
"""

from .config import BehaviorLabConfig, load_config
from .facade import read_health, read_live_state, read_signals, run_backtest

__all__ = [
    "BehaviorLabConfig",
    "load_config",
    "read_health",
    "read_live_state",
    "read_signals",
    "run_backtest",
]

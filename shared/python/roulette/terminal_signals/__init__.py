"""Motor compartilhado dos sinais de terminais A, B, Cruzado e Gêmeos."""

from .catalog import ENGINE_VERSION, VARIANTS, get_variant
from .engine import (
    PatternAnalysis,
    SignalCandidate,
    analyze_motor_a,
    analyze_motor_b,
    compute_cross_targets,
    compute_terminal_targets,
    detect_variant,
)

__all__ = [
    "ENGINE_VERSION",
    "VARIANTS",
    "PatternAnalysis",
    "SignalCandidate",
    "analyze_motor_a",
    "analyze_motor_b",
    "compute_cross_targets",
    "compute_terminal_targets",
    "detect_variant",
    "get_variant",
]

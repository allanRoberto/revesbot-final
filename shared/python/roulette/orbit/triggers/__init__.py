"""Estrategias prospectivas de entrada construidas sobre o motor orbital."""

from .catalog import STRATEGIES, TriggerStrategySpec, get_strategy
from .state_machine import (
    CandidateTransition,
    TriggerActivation,
    advance_candidate,
    advance_trigger_trial_document,
    build_ryan_entry,
    build_ryan2_entry,
    expand_with_neighbors,
)

__all__ = [
    "STRATEGIES",
    "CandidateTransition",
    "TriggerActivation",
    "TriggerStrategySpec",
    "advance_candidate",
    "advance_trigger_trial_document",
    "build_ryan_entry",
    "build_ryan2_entry",
    "expand_with_neighbors",
    "get_strategy",
]

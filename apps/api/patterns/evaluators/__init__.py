from __future__ import annotations

from typing import Any, Callable, Dict, List

from . import terminal_repeat_sum_neighbors as terminal_repeat_sum_neighbors_module
from . import terminal_repeat_wait_spins_neighbors as terminal_repeat_wait_spins_neighbors_module
from . import terminal_repeat_next_sum_wait_neighbors as terminal_repeat_next_sum_wait_neighbors_module
from . import skipped_sequence_target_neighbors as skipped_sequence_target_neighbors_module
from . import anchor_return_target_neighbors_mirrors as anchor_return_target_neighbors_mirrors_module
from . import exact_repeat_delayed_entry as exact_repeat_delayed_entry_module
from . import neighbor_repeat_delayed_entry as neighbor_repeat_delayed_entry_module
from . import terminal_repeat_sum_delayed_entry as terminal_repeat_sum_delayed_entry_module
from . import repeat_trend_next_projection_delayed_entry as repeat_trend_next_projection_delayed_entry_module
from . import exact_alternation_delayed_entry as exact_alternation_delayed_entry_module
from . import color_neighbor_alternation_missing_entry as color_neighbor_alternation_missing_entry_module
from . import terminal_alternation_middle_entry as terminal_alternation_middle_entry_module
from . import trend_alternation_middle_projection_entry as trend_alternation_middle_projection_entry_module
from . import terminal_alternation_target_neighbors as terminal_alternation_target_neighbors_module
from . import terminal_group_rotation_369_147_258 as terminal_group_rotation_369_147_258_module
from . import sector_alternation_boost as sector_alternation_boost_module
from . import local_transition_protection as local_transition_protection_module
from . import siege_number_boost as siege_number_boost_module
from . import recent_numbers_penalty as recent_numbers_penalty_module
from . import cold_sector_penalty as cold_sector_penalty_module
from . import legacy_base_suggestion as legacy_base_suggestion_module
from . import robust_multi_model as robust_multi_model_module
from . import color_streak_boost as color_streak_boost_module
from . import dozen_column_streak_boost as dozen_column_streak_boost_module
from . import parity_streak_boost as parity_streak_boost_module
from . import sector_repeat_penalty as sector_repeat_penalty_module
from . import hot_numbers_decay_boost as hot_numbers_decay_boost_module
from . import high_low_streak_boost as high_low_streak_boost_module
from . import sleeping_numbers_boost as sleeping_numbers_boost_module
from . import wheel_sector_momentum as wheel_sector_momentum_module
from . import maquina_mortifera_sector_memory as maquina_mortifera_sector_memory_module
from . import wheel_neighbors_5 as wheel_neighbors_5_module
from . import consecutive_gap_boost as consecutive_gap_boost_module
from . import wheel_cluster_penalty as wheel_cluster_penalty_module
from . import finals_pattern_boost as finals_pattern_boost_module
from . import volatility_detector as volatility_detector_module
from . import repeat_distance_boost as repeat_distance_boost_module
from . import context_history_boost as context_history_boost_module
from . import master_pattern_boost as master_pattern_boost_module
from . import estelar_equivalence_boost as estelar_equivalence_boost_module
from . import chain_behavior_boost as chain_behavior_boost_module
from . import cavalos_faltantes_boost as cavalos_faltantes_boost_module
from . import gemeos_boost as gemeos_boost_module
from . import terminais_iguais_boost as terminais_iguais_boost_module
from . import puxou_cavalo_boost as puxou_cavalo_boost_module
from . import sequencia_pulada_0369_boost as sequencia_pulada_0369_boost_module
from . import alinhamento_boost as alinhamento_boost_module
from . import alinhamento_final_boost as alinhamento_final_boost_module
from . import alinhamento_total_boost as alinhamento_total_boost_module
from . import numero_quente_boost as numero_quente_boost_module
from . import patchoko_rep_boost as patchoko_rep_boost_module
from . import patchoko_seq_boost as patchoko_seq_boost_module
from . import blackhorse_boost as blackhorse_boost_module
from . import puxados_boost as puxados_boost_module
from . import numeros_puxando_boost as numeros_puxando_boost_module
from . import score_boost as score_boost_module
from . import legacy_processing_bridge as legacy_processing_bridge_module

_EVALUATORS: Dict[str, Callable[..., Dict[str, Any]]] = {
    "terminal_repeat_sum_neighbors": terminal_repeat_sum_neighbors_module.evaluate,
    "terminal_repeat_wait_spins_neighbors": terminal_repeat_wait_spins_neighbors_module.evaluate,
    "terminal_repeat_next_sum_wait_neighbors": terminal_repeat_next_sum_wait_neighbors_module.evaluate,
    "skipped_sequence_target_neighbors": skipped_sequence_target_neighbors_module.evaluate,
    "anchor_return_target_neighbors_mirrors": anchor_return_target_neighbors_mirrors_module.evaluate,
    "exact_repeat_delayed_entry": exact_repeat_delayed_entry_module.evaluate,
    "neighbor_repeat_delayed_entry": neighbor_repeat_delayed_entry_module.evaluate,
    "terminal_repeat_sum_delayed_entry": terminal_repeat_sum_delayed_entry_module.evaluate,
    "repeat_trend_next_projection_delayed_entry": repeat_trend_next_projection_delayed_entry_module.evaluate,
    "exact_alternation_delayed_entry": exact_alternation_delayed_entry_module.evaluate,
    "color_neighbor_alternation_missing_entry": color_neighbor_alternation_missing_entry_module.evaluate,
    "terminal_alternation_middle_entry": terminal_alternation_middle_entry_module.evaluate,
    "trend_alternation_middle_projection_entry": trend_alternation_middle_projection_entry_module.evaluate,
    "terminal_alternation_target_neighbors": terminal_alternation_target_neighbors_module.evaluate,
    "terminal_group_rotation_369_147_258": terminal_group_rotation_369_147_258_module.evaluate,
    "sector_alternation_boost": sector_alternation_boost_module.evaluate,
    "local_transition_protection": local_transition_protection_module.evaluate,
    "siege_number_boost": siege_number_boost_module.evaluate,
    "recent_numbers_penalty": recent_numbers_penalty_module.evaluate,
    "cold_sector_penalty": cold_sector_penalty_module.evaluate,
    "legacy_base_suggestion": legacy_base_suggestion_module.evaluate,
    "robust_multi_model": robust_multi_model_module.evaluate,
    "color_streak_boost": color_streak_boost_module.evaluate,
    "dozen_column_streak_boost": dozen_column_streak_boost_module.evaluate,
    "parity_streak_boost": parity_streak_boost_module.evaluate,
    "sector_repeat_penalty": sector_repeat_penalty_module.evaluate,
    "hot_numbers_decay_boost": hot_numbers_decay_boost_module.evaluate,
    "high_low_streak_boost": high_low_streak_boost_module.evaluate,
    "sleeping_numbers_boost": sleeping_numbers_boost_module.evaluate,
    "wheel_sector_momentum": wheel_sector_momentum_module.evaluate,
    "maquina_mortifera_sector_memory": maquina_mortifera_sector_memory_module.evaluate,
    "wheel_neighbors_5": wheel_neighbors_5_module.evaluate,
    "consecutive_gap_boost": consecutive_gap_boost_module.evaluate,
    "wheel_cluster_penalty": wheel_cluster_penalty_module.evaluate,
    "finals_pattern_boost": finals_pattern_boost_module.evaluate,
    "volatility_detector": volatility_detector_module.evaluate,
    "repeat_distance_boost": repeat_distance_boost_module.evaluate,
    "context_history_boost": context_history_boost_module.evaluate,
    "master_pattern_boost": master_pattern_boost_module.evaluate,
    "estelar_equivalence_boost": estelar_equivalence_boost_module.evaluate,
    "chain_behavior_boost": chain_behavior_boost_module.evaluate,
    "cavalos_faltantes_boost": cavalos_faltantes_boost_module.evaluate,
    "gemeos_boost": gemeos_boost_module.evaluate,
    "terminais_iguais_boost": terminais_iguais_boost_module.evaluate,
    "puxou_cavalo_boost": puxou_cavalo_boost_module.evaluate,
    "sequencia_pulada_0369_boost": sequencia_pulada_0369_boost_module.evaluate,
    "alinhamento_boost": alinhamento_boost_module.evaluate,
    "alinhamento_final_boost": alinhamento_final_boost_module.evaluate,
    "alinhamento_total_boost": alinhamento_total_boost_module.evaluate,
    "numero_quente_boost": numero_quente_boost_module.evaluate,
    "patchoko_rep_boost": patchoko_rep_boost_module.evaluate,
    "patchoko_seq_boost": patchoko_seq_boost_module.evaluate,
    "blackhorse_boost": blackhorse_boost_module.evaluate,
    "puxados_boost": puxados_boost_module.evaluate,
    "numeros_puxando_boost": numeros_puxando_boost_module.evaluate,
    "score_boost": score_boost_module.evaluate,
    "legacy_processing_bridge": legacy_processing_bridge_module.evaluate,
}

def build_evaluator_registry(engine: Any) -> Dict[str, Callable[[List[int], List[int], int, Any, int | None], Dict[str, Any]]]:
    registry: Dict[str, Callable[[List[int], List[int], int, Any, int | None], Dict[str, Any]]] = {}
    for pattern_id, evaluator in _EVALUATORS.items():
        registry[pattern_id] = (
            lambda history, base_suggestion, from_index, definition, focus_number=None, _ev=evaluator:
            _ev(engine, history, base_suggestion, from_index, definition, focus_number)
        )
    return registry

__all__ = ["build_evaluator_registry"]

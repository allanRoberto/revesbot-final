# Dynamic Weighting Shadow Replay Report

Generated at: 2026-03-10T11:48:27.233160+00:00
Mode: SMOKE/PREVIEW

## Scope
- Shadow only: no production runtime changes.
- Data source: `/history/{slug}`.

## Input Summary
- Base URL: `https://api.revesbot.com.br`
- Global input hash: `adbbbd462f719e1d889a107b2e497122343fbb089adfa448c23094fdf336b154`
- Holdout leakage fallback: `True`
- Evaluation cases: `80`
- Windows: `[100, 200, 500]`

### Roulettes
- pragmatic-auto-mega-roulette: count=140, order=most_recent_first, order_confirmed=False, hash=c10ebc7978f01856c45df282fc140464ac720c6dedf6ab797b87267e341b0777
- pragmatic-auto-roulette: count=140, order=most_recent_first, order_confirmed=False, hash=0aca611ecabd11c973e681186154e20cf8282c59ec4154da9fd91f819198d83b

## Scenario Comparison
| Scenario | coverage | e_hit@1 | e_hit@2 | e_hit@3 | e_hit@4 | avg_list_size |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 1.0000 | 0.3500 | 0.5750 | 0.7625 | 0.8375 | 12.000 |
| candidate_w100 | 1.0000 | 0.3500 | 0.5875 | 0.7750 | 0.8250 | 12.000 |
| candidate_w200 | 1.0000 | 0.3500 | 0.5875 | 0.7750 | 0.8250 | 12.000 |
| candidate_w500 | 1.0000 | 0.3500 | 0.5875 | 0.7750 | 0.8250 | 12.000 |

## Ablation (selected scenario)
- Scenario: `candidate_w200`
- Patterns analyzed: `36`

### Top Positive Delta (remove pattern hurts)
| pattern_id | sample_size | delta_coverage | delta_effective_hit@4_remove_pattern |
|---|---:|---:|---:|
| alinhamento_boost | 80 | 0.000000 | 0.075000 |
| estelar_equivalence_boost | 80 | 0.000000 | 0.025000 |
| finals_pattern_boost | 59 | 0.000000 | 0.012500 |
| legacy_base_suggestion | 78 | 0.000000 | 0.012500 |
| patchoko_seq_boost | 8 | 0.000000 | 0.012500 |
| sleeping_numbers_boost | 80 | 0.000000 | 0.012500 |
| anchor_return_target_neighbors_mirrors | 80 | 0.000000 | 0.000000 |
| blackhorse_boost | 10 | 0.000000 | 0.000000 |
| cavalos_faltantes_boost | 14 | 0.000000 | 0.000000 |
| chain_behavior_boost | 60 | 0.000000 | 0.000000 |

### Top Negative Delta (remove pattern improves)
| pattern_id | sample_size | delta_coverage | delta_effective_hit@4_remove_pattern |
|---|---:|---:|---:|
| numero_quente_boost | 80 | 0.000000 | -0.012500 |
| context_history_boost | 71 | 0.000000 | -0.012500 |
| alinhamento_total_boost | 71 | 0.000000 | -0.012500 |
| alinhamento_final_boost | 44 | 0.000000 | -0.012500 |
| wheel_sector_momentum | 23 | 0.000000 | 0.000000 |
| volatility_detector | 80 | 0.000000 | 0.000000 |
| terminal_repeat_wait_target_neighbors | 8 | 0.000000 | 0.000000 |
| terminal_repeat_sum_neighbors | 10 | 0.000000 | 0.000000 |
| terminal_repeat_next_sum_wait_neighbors | 8 | 0.000000 | 0.000000 |
| terminal_alternation_target_neighbors | 7 | 0.000000 | 0.000000 |

## Notes
- This report is generated from API history and is reproducible via input hash + config.
- Promotion to production remains manual after objective validation criteria.

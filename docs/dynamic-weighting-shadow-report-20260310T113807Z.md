# Dynamic Weighting Shadow Replay Report

Generated at: 2026-03-10T11:38:07.184496+00:00
Mode: SMOKE/PREVIEW

## Scope
- Shadow only: no production runtime changes.
- Data source: `/history/{slug}`.

## Input Summary
- Base URL: `https://api.revesbot.com.br`
- Global input hash: `336f6b60eb845526b67edb63ecdb2211b4cd16c1d78d5d2ce71bcddfc20d52f5`
- Holdout leakage fallback: `True`
- Evaluation cases: `40`
- Windows: `[100, 200, 500]`

### Roulettes
- pragmatic-auto-mega-roulette: count=120, order=most_recent_first, order_confirmed=False, hash=a97dadbedc4e13ec45001f869e147ee12638c8b73531af8840dbcebb5ae2db00
- pragmatic-auto-roulette: count=120, order=most_recent_first, order_confirmed=False, hash=dd5f3162f20fb001611d43410c812cb09cb6041b966eaeb4c00336a228cf3595

## Scenario Comparison
| Scenario | coverage | e_hit@1 | e_hit@2 | e_hit@3 | e_hit@4 | avg_list_size |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 1.0000 | 0.4000 | 0.6250 | 0.7750 | 0.8750 | 12.000 |
| candidate_w100 | 1.0000 | 0.4000 | 0.6250 | 0.7750 | 0.8750 | 12.000 |
| candidate_w200 | 1.0000 | 0.4000 | 0.6250 | 0.7750 | 0.8750 | 12.000 |
| candidate_w500 | 1.0000 | 0.4000 | 0.6250 | 0.7750 | 0.8750 | 12.000 |

## Ablation (selected scenario)
- Scenario: `candidate_w200`
- Patterns analyzed: `8`

### Top Positive Delta (remove pattern hurts)
| pattern_id | sample_size | delta_coverage | delta_effective_hit@4_remove_pattern |
|---|---:|---:|---:|
| hot_numbers_decay_boost | 40 | 0.000000 | 0.025000 |
| numero_quente_boost | 40 | 0.000000 | 0.025000 |
| anchor_return_target_neighbors_mirrors | 40 | 0.000000 | 0.000000 |
| consecutive_gap_boost | 40 | 0.000000 | 0.000000 |
| estelar_equivalence_boost | 40 | 0.000000 | 0.000000 |
| sleeping_numbers_boost | 40 | 0.000000 | 0.000000 |
| volatility_detector | 40 | 0.000000 | 0.000000 |
| alinhamento_boost | 40 | 0.000000 | -0.025000 |

## Notes
- This report is generated from API history and is reproducible via input hash + config.
- Promotion to production remains manual after objective validation criteria.

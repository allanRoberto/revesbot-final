# Dynamic Weighting Shadow Replay Report

Generated at: 2026-03-10T11:38:48.053248+00:00
Mode: SMOKE/PREVIEW

## Scope
- Shadow only: no production runtime changes.
- Data source: `/history/{slug}`.

## Input Summary
- Base URL: `https://api.revesbot.com.br`
- Global input hash: `2f7726edce3f2b001fabf489e99051766090278258bc080bece4ae11b0c96d51`
- Holdout leakage fallback: `True`
- Evaluation cases: `40`
- Windows: `[100, 200, 500]`

### Roulettes
- pragmatic-auto-roulette: count=120, order=most_recent_first, order_confirmed=False, hash=beb5aa33eadab708b2f47930557a0e524c4336a06519aa0460f7dcec0cf860e5
- pragmatic-brazilian-roulette: count=120, order=most_recent_first, order_confirmed=False, hash=05a7e6586cc84953dc3b2475ac0328ecc7bffff5d35580e3e17505cd4acecbee

## Scenario Comparison
| Scenario | coverage | e_hit@1 | e_hit@2 | e_hit@3 | e_hit@4 | avg_list_size |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 1.0000 | 0.3250 | 0.6250 | 0.8500 | 0.9250 | 12.000 |
| candidate_w100 | 1.0000 | 0.3250 | 0.6250 | 0.8500 | 0.9250 | 12.000 |
| candidate_w200 | 1.0000 | 0.3250 | 0.6250 | 0.8500 | 0.9250 | 12.000 |
| candidate_w500 | 1.0000 | 0.3250 | 0.6250 | 0.8500 | 0.9250 | 12.000 |

## Ablation (selected scenario)
- Scenario: `candidate_w200`
- Patterns analyzed: `8`

### Top Positive Delta (remove pattern hurts)
| pattern_id | sample_size | delta_coverage | delta_effective_hit@4_remove_pattern |
|---|---:|---:|---:|
| alinhamento_boost | 40 | 0.000000 | 0.100000 |
| consecutive_gap_boost | 40 | 0.000000 | 0.025000 |
| numero_quente_boost | 40 | 0.000000 | 0.025000 |
| sleeping_numbers_boost | 40 | 0.000000 | 0.025000 |
| anchor_return_target_neighbors_mirrors | 40 | 0.000000 | 0.000000 |
| estelar_equivalence_boost | 40 | 0.000000 | 0.000000 |
| hot_numbers_decay_boost | 40 | 0.000000 | 0.000000 |
| volatility_detector | 40 | 0.000000 | 0.000000 |

## Notes
- This report is generated from API history and is reproducible via input hash + config.
- Promotion to production remains manual after objective validation criteria.

# Dynamic Weighting Shadow Replay Report

Generated at: 2026-03-10T11:36:12.630229+00:00
Mode: SMOKE/PREVIEW

## Scope
- Shadow only: no production runtime changes.
- Data source: `/history/{slug}`.

## Input Summary
- Base URL: `https://api.revesbot.com.br`
- Global input hash: `62f9dae1bd759483aa85b6a68100b273949f0cba8e470d148b27e554f7e6a8da`
- Holdout leakage fallback: `True`
- Evaluation cases: `4`
- Windows: `[100, 200, 500]`

### Roulettes
- pragmatic-auto-roulette: count=60, order=most_recent_first, order_confirmed=False, hash=ea880ea5a38d1328eedc959974d4b0f349d6a93a3f2df50a75b8df4235dcd05d
- pragmatic-brazilian-roulette: count=60, order=most_recent_first, order_confirmed=False, hash=a89826240dd02a3a8f0b61bc9b60edb937e936666c2ccd2db9f7e7b39d6ec3cf

## Scenario Comparison
| Scenario | coverage | e_hit@1 | e_hit@2 | e_hit@3 | e_hit@4 | avg_list_size |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 1.0000 | 0.2500 | 0.7500 | 0.7500 | 0.7500 | 12.000 |
| candidate_w100 | 1.0000 | 0.2500 | 0.7500 | 0.7500 | 0.7500 | 12.000 |
| candidate_w200 | 1.0000 | 0.2500 | 0.7500 | 0.7500 | 0.7500 | 12.000 |
| candidate_w500 | 1.0000 | 0.2500 | 0.7500 | 0.7500 | 0.7500 | 12.000 |

## Ablation (selected scenario)
- Scenario: `candidate_w200`
- Patterns analyzed: `2`

### Top Positive Delta (remove pattern hurts)
| pattern_id | sample_size | delta_coverage | delta_effective_hit@4_remove_pattern |
|---|---:|---:|---:|
| anchor_return_target_neighbors_mirrors | 4 | 0.000000 | -0.250000 |
| estelar_equivalence_boost | 4 | 0.000000 | -0.250000 |

## Notes
- This report is generated from API history and is reproducible via input hash + config.
- Promotion to production remains manual after objective validation criteria.

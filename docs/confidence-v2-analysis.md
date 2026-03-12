# Confidence V2 Analysis

Generated at: 2026-03-11T11:42:44.522586Z
Source mode: `snapshot_cache`
Eligible cases: `400`

## Source
- source type: `snapshot_cache`
- histories used: `5`
- details: `{'snapshot_dir': 'apps/api/data/confidence_history_snapshots', 'derived_from': '/history/{slug}'}`
- calibration cases: `600`
- evaluation cases: `400`

## Baseline vs V2
- current coverage: `1.0`
- current conditional_hit@4: `0.7175`
- current effective_hit@4: `0.7175`
- current ECE hit@4: `0.206475`
- v2 coverage: `1.0`
- v2 conditional_hit@4: `0.7175`
- v2 effective_hit@4: `0.7175`
- v2 ECE hit@4: `0.017625`

## Current Confidence Buckets
| Bucket | Casos | Coverage | Conditional Hit@4 | Effective Hit@4 |
|---|---:|---:|---:|---:|
| 100-100 | 1 | 0.003 | 1.000000 | 0.003 |
| 80-89 | 55 | 0.138 | 0.781818 | 0.107 |
| 90-99 | 344 | 0.860 | 0.706395 | 0.608 |

## V2 Confidence Buckets
| Bucket | Casos | Coverage | Conditional Hit@4 | Effective Hit@4 |
|---|---:|---:|---:|---:|
| 70-79 | 400 | 1.000 | 0.717500 | 0.718 |

## Current Threshold Coverage
| Threshold | Casos | Coverage | Conditional Hit@4 | Effective Hit@4 |
|---|---:|---:|---:|---:|
| >=40 | 400 | 1.000 | 0.717500 | 0.718 |
| >=50 | 400 | 1.000 | 0.717500 | 0.718 |
| >=60 | 400 | 1.000 | 0.717500 | 0.718 |
| >=70 | 400 | 1.000 | 0.717500 | 0.718 |

## V2 Threshold Coverage
| Threshold | Casos | Coverage | Conditional Hit@4 | Effective Hit@4 |
|---|---:|---:|---:|---:|
| >=40 | 400 | 1.000 | 0.717500 | 0.718 |
| >=50 | 400 | 1.000 | 0.717500 | 0.718 |
| >=60 | 400 | 1.000 | 0.717500 | 0.718 |
| >=70 | 400 | 1.000 | 0.717500 | 0.718 |

## Calibration Notes
- `confidence_v2` permanece em shadow mode.
- `confidence` atual continua sendo a score operacional de produção.
- A calibracao v2 usa bucket de `merged_raw_v2` com shrinkage por volume do bucket.

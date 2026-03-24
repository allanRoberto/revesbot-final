# Confidence V2 Analysis

Generated at: 2026-03-22T23:31:10.965412Z
Source mode: `snapshot_cache`
Eligible cases: `800`

## Source
- source type: `snapshot_cache`
- histories used: `5`
- details: `{'snapshot_dir': 'apps/api/data/confidence_history_snapshots', 'derived_from': '/history/{slug}'}`
- calibration cases: `1200`
- evaluation cases: `800`

## Baseline vs V2
- current coverage: `1.0`
- current conditional_hit@4: `0.78125`
- current effective_hit@4: `0.78125`
- current ECE hit@4: `0.14045`
- v2 coverage: `1.0`
- v2 conditional_hit@4: `0.78125`
- v2 effective_hit@4: `0.78125`
- v2 ECE hit@4: `0.07585`

## Current Confidence Buckets
| Bucket | Casos | Coverage | Conditional Hit@4 | Effective Hit@4 |
|---|---:|---:|---:|---:|
| 100-100 | 3 | 0.004 | 0.666667 | 0.003 |
| 80-89 | 142 | 0.177 | 0.774648 | 0.138 |
| 90-99 | 655 | 0.819 | 0.783206 | 0.641 |

## V2 Confidence Buckets
| Bucket | Casos | Coverage | Conditional Hit@4 | Effective Hit@4 |
|---|---:|---:|---:|---:|
| 70-79 | 800 | 1.000 | 0.781250 | 0.781 |

## Current Threshold Coverage
| Threshold | Casos | Coverage | Conditional Hit@4 | Effective Hit@4 |
|---|---:|---:|---:|---:|
| >=40 | 800 | 1.000 | 0.781250 | 0.781 |
| >=50 | 800 | 1.000 | 0.781250 | 0.781 |
| >=60 | 800 | 1.000 | 0.781250 | 0.781 |
| >=70 | 800 | 1.000 | 0.781250 | 0.781 |

## V2 Threshold Coverage
| Threshold | Casos | Coverage | Conditional Hit@4 | Effective Hit@4 |
|---|---:|---:|---:|---:|
| >=40 | 800 | 1.000 | 0.781250 | 0.781 |
| >=50 | 800 | 1.000 | 0.781250 | 0.781 |
| >=60 | 800 | 1.000 | 0.781250 | 0.781 |
| >=70 | 800 | 1.000 | 0.781250 | 0.781 |

## Calibration Notes
- `confidence_v2` permanece em shadow mode.
- `confidence` atual continua sendo a score operacional de produção.
- A calibracao v2 usa bucket de `merged_raw_v2` com shrinkage por volume do bucket.
- A pontuacao calibrada prioriza buckets com acerto mais cedo (`hit@1`, `hit@2`) e penaliza buckets com primeiro hit tardio.

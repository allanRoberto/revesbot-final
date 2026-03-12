# Dynamic Weighting Shadow Replay Report

Generated at: 2026-03-10T15:04:22.406556+00:00
Mode: FULL
Stage: intermediate

## Scope
- Shadow only: no production runtime changes.
- Data source: `/history/{slug}`.

## Input Summary
- Base URL: `https://api.revesbot.com.br`
- Seed: `20260310`
- Global input hash: `7855caea71021b3beef8d42db4e4c997214c707db5d4c7dc63564389a8e55f52`
- Holdout leakage fallback: `False`
- Total de casos avaliados: `960`
- Windows: `[100, 200, 500]`
- Roulettes usadas: `8`
- Roulettes descartadas: `0`

### Roulettes usadas
- pragmatic-auto-mega-roulette: count=800, order=most_recent_first, order_confirmed=True, check_source=history-single-vs-multi, hash=7022d874cbce9b819d257d1d89a88f0431b93901ec5e814698e9cb7f0c99c72d
- pragmatic-auto-roulette: count=800, order=most_recent_first, order_confirmed=True, check_source=history-single-vs-multi, hash=398a6c2cc07ef885766ef1d16b3f6a6e8deafb96cbad2a51f53fc0fee4ada1d2
- pragmatic-brazilian-roulette: count=800, order=most_recent_first, order_confirmed=True, check_source=history-single-vs-multi, hash=8954b141f695931d4d6e994b7597188b7c2dc098d67e85516cfce04fcbc0acf1
- pragmatic-german-roulette: count=800, order=most_recent_first, order_confirmed=True, check_source=history-single-vs-multi, hash=71b209cd9509b52db98ff2b3f918af41d15ea53efd1cf4c738326ba046566628
- pragmatic-immersive-roulette-deluxe: count=800, order=most_recent_first, order_confirmed=True, check_source=history-single-vs-multi, hash=2d26eae15bd7c02ff9b6d5b55748285efe89c0987bb260f5e9b171d2534b3054
- pragmatic-korean-roulette: count=800, order=most_recent_first, order_confirmed=True, check_source=history-single-vs-multi, hash=6403e5ccaef66b106bf73873a93d9a4531780f57a177edce4c045a19dab9e1ce
- pragmatic-mega-roulette: count=800, order=most_recent_first, order_confirmed=True, check_source=history-single-vs-multi, hash=2dd974d150c56b977931b800c809ef961eaf7a24ad8a8d71392ca833eac346bb
- pragmatic-vip-roulette: count=800, order=most_recent_first, order_confirmed=True, check_source=history-single-vs-multi, hash=9baede3cbdd9a1a733ee2186e9b50149e39e85d6c6f5a13d6f2eb662616da082

### Roulettes descartadas
- nenhuma

## Scenario Comparison
| Scenario | coverage | e_hit@1 | e_hit@2 | e_hit@3 | e_hit@4 | avg_list_size |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 0.9906 | 0.3031 | 0.5135 | 0.6781 | 0.7844 | 11.981 |
| candidate_w100 | 0.9906 | 0.3031 | 0.5135 | 0.6760 | 0.7833 | 11.981 |
| candidate_w200 | 0.9906 | 0.3031 | 0.5135 | 0.6760 | 0.7833 | 11.981 |
| candidate_w500 | 0.9906 | 0.3052 | 0.5146 | 0.6771 | 0.7833 | 11.981 |

## Intermediate Assessment
- Total de casos avaliados: `960`
- Melhor janela/candidate até agora: `candidate_w100` (effective_hit@4=0.783333)
- Diferença para 2o colocado: `0.000000`
- candidate_w200: `0.783333`
- Suficiência de sinal nesta rodada: **sinal estatístico inicial, ainda com cautela**
- Padrões aparentemente agregadores (ablação): `0`
- Padrões aparentemente neutros (ablação): `2`
- Padrões aparentemente prejudiciais (ablação): `4`

## Ablation (selected scenario)
- Scenario: `candidate_w200`
- Patterns analyzed: `10`

### Top Positive Delta (remove pattern hurts)
| pattern_id | sample_size | delta_coverage | delta_effective_hit@4_remove_pattern |
|---|---:|---:|---:|
| hot_numbers_decay_boost | 913 | 0.000000 | 0.001041 |
| master_pattern_boost | 780 | 0.000000 | 0.001041 |
| volatility_detector | 890 | 0.000000 | 0.001041 |
| consecutive_gap_boost | 890 | 0.000000 | 0.000000 |
| legacy_base_suggestion | 830 | 0.000000 | 0.000000 |
| sleeping_numbers_boost | 830 | 0.000000 | -0.001042 |
| alinhamento_boost | 794 | 0.000000 | -0.003125 |
| anchor_return_target_neighbors_mirrors | 877 | 0.000000 | -0.003125 |
| estelar_equivalence_boost | 923 | 0.000000 | -0.004167 |
| numero_quente_boost | 798 | 0.000000 | -0.004167 |

## Notes
- This report is generated from API history and is reproducible via input hash + config.
- Promotion to production remains manual after objective validation criteria.

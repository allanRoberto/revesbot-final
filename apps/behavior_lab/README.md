# Behavior Lab

Motor Python independente para observar apenas os resultados da mesa
`pragmatic-auto-roulette`. Ele não importa lógica de `signals`, `monitoring`,
`patterns`, `orbit` ou `collector`.

## Garantias causais

- cada decisão é registrada antes do resultado que a avalia;
- o giro ativador só cria um sinal para o giro seguinte;
- todo resultado legítimo consome uma tentativa, mesmo que repita o número;
- somente `_id` ou `external_game_id` já processado é retransmissão;
- o décimo giro ainda pode vencer; o décimo erro perde;
- sinal sem dez giros no fim de um backtest é `censored`;
- `NO_BET` é uma decisão normal quando não há sinal.

## Regras v1

- `exact_pair_continuation`: quando um par ordenado diferente reaparece, usa os
  três resultados posteriores à ocorrência anterior;
- `repeated_same_double`: quando o mesmo duplo `X,X` reaparece, usa os três
  resultados posteriores ao duplo anterior;
- `structural_21_terminal1_double`: compara formações `21`, zero ou uma
  inserção, terminal `1/11/31` e um duplo; usa quatro resultados posteriores à
  formação anterior.

Antes da ativação, um alvo cuja região já apareceu nos oito resultados mais
recentes é marcado como esgotado e removido. A região de pagamento contém o
alvo, seus vizinhos físicos imediatos e, apenas para 13/31, o espelho
configurado. O desempate auditável é exato, vizinho e depois espelho.

## Execução

```bash
PYTHONPATH=apps python -m behavior_lab worker
PYTHONPATH=apps python -m behavior_lab backtest --file resultados.json --input-order newest-first
PYTHONPATH=apps python -m behavior_lab backtest --api --limit 5000
```

O worker recebe notificações em `/ws?slug=...`, mas ingere somente a sequência
persistida de `/history/pragmatic-auto-roulette`; assim, perdas ou retransmissões
do socket não alteram a ordem causal. Ele grava somente estado derivado sob
`behavior_lab:v1:pragmatic-auto-roulette:*`.

Variáveis operacionais: `BEHAVIOR_LAB_CONFIG`, `BEHAVIOR_LAB_API_BASE_URL`,
`BEHAVIOR_LAB_WS_URL`, `BEHAVIOR_LAB_REDIS_URL`,
`BEHAVIOR_LAB_RECONCILE_INTERVAL_SECONDS` e `BEHAVIOR_LAB_LOG_LEVEL`.
Se `BEHAVIOR_LAB_REDIS_URL` não estiver presente, o worker e a facade usam
`REDIS_CONNECT` antes do fallback local.

# Monitor de Terminais A, B, Cruzado e Gêmeos

## Objetivo

Monitorar prospectivamente, sem publicar apostas, as seis variações derivadas do
arquivo `TERMINAIS CRUZADO + GEMEOS`:

- `motor-a-seco`
- `motor-a-vizinhos`
- `motor-b-seco`
- `motor-b-vizinhos`
- `cruzado`
- `gemeos`

O giro que forma o sinal é apenas a ativação. G1 começa no giro seguinte.

## Runtime

O mesmo entrypoint é executado pelo PM2 uma vez para cada variação:

```bash
TERMINAL_SIGNAL_VARIANT=cruzado \
TERMINAL_SIGNAL_ROULETTE_IDS=all \
./.venv/bin/python apps/monitoring/scripts/terminal_signal_worker.py
```

Variáveis:

| Variável | Padrão | Uso |
|---|---:|---|
| `TERMINAL_SIGNAL_VARIANT` | obrigatório | Uma das seis variações |
| `TERMINAL_SIGNAL_ROULETTE_IDS` | `all` | `all` ou slugs separados por vírgula |
| `TERMINAL_SIGNAL_HISTORY_LIMIT` | `500` | Histórico em memória por mesa |
| `TERMINAL_SIGNAL_MAX_ATTEMPTS` | `2` | Horizonte prospectivo |
| `TERMINAL_SIGNAL_RECONCILE_SECONDS` | `5` | Reconciliação do Mongo |
| `TERMINAL_SIGNAL_DISCOVERY_SECONDS` | `60` | Descoberta de novas mesas |
| `RESULT_CHANNEL` | `new_result` | Canal Redis usado como acelerador |

Redis reduz a latência, mas MongoDB `history` é a fonte autoritativa. O offset de
cada worker/mesa fica em `terminal_signal_worker_state`, e os resultados ficam em
`terminal_signal_trials`.

## Garantias de consistência

- `event_id` possui índice único.
- Cada tentativa guarda o `_id` do giro em `attempt_history_ids`.
- A ativação nunca pode ser usada como tentativa.
- O offset só avança depois que o giro foi aplicado.
- No primeiro start, o worker começa no giro mais recente e não mistura replay
  retroativo com a coorte prospectiva.
- Depois de restart, sinais `pending` e giros posteriores ao offset são retomados.

## API e dashboard

Dashboard:

```text
/sinais-terminais
```

Endpoints:

```text
GET  /api/terminal-signals/catalog
GET  /api/terminal-signals/summary
GET  /api/terminal-signals/history
POST /api/terminal-signals/profitability
```

O seletor de mesa usa todas as entradas `pragmatic-*` existentes em `history`.
A resposta de assertividade inclui a expectativa aleatória calculada pela
quantidade de alvos de cada formação.

## Lucratividade

O padrão do HTML usa ficha por número:

- G1: `1`
- G2: `1.5`
- retorno bruto: `36x`

O endpoint também aceita `payout_mode=table_base`, que usa `30x` para as mesas
Mega conhecidas e `36x` para as demais. O cálculo usa a quantidade real de alvos
e ordena os fluxos de caixa pelo horário das tentativas, incluindo simultaneidade.

## Operação PM2

Os processos são adicionados por `infra/pm2/ecosystem.config.js` quando
`TERMINAL_SIGNALS_ENABLED` não é `0`.

Exemplos:

```bash
DEPLOY_STAGE=main pm2 startOrReload infra/pm2/ecosystem.config.js
pm2 logs terminal-cruzado-prod
pm2 logs terminal-gemeos-prod
```

Para desativar todo o conjunto:

```bash
TERMINAL_SIGNALS_ENABLED=0 DEPLOY_STAGE=main pm2 startOrReload infra/pm2/ecosystem.config.js
```

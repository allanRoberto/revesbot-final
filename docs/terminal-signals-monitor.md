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

O giro que forma o sinal é apenas a ativação. T1 começa no giro seguinte. Cada
formação coleta sempre T1–T10, mesmo que haja acerto antes, para permitir
simulações posteriores sem perder observações.

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
| `TERMINAL_SIGNAL_MAX_ATTEMPTS` | `10` | Horizonte de coleta prospectiva |
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
- Depois de restart, coletas `collecting` e giros posteriores ao offset são retomados.
- Um acerto não encerra a coleta bruta; apenas define `first_hit_attempt`.
- Cada giro avança todas as formações abertas da mesa antes de detectar uma nova.
- Novas formações nunca aguardam as anteriores terminarem, portanto os sinais se
  sobrepõem sem perder a relação número a número.

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
POST /api/terminal-signals/scenarios
```

O seletor de mesa usa todas as entradas `pragmatic-*` existentes em `history`.
A resposta de assertividade inclui a expectativa aleatória calculada pela
quantidade de alvos de cada formação.

## Simulação T2–T10 e lucratividade

O padrão do HTML usa ficha por número:

- T1: `1`
- T2: `1.5`
- T3–T10: `1.5` por padrão, editáveis no painel
- retorno bruto: `36x`

O endpoint `/scenarios` compara os horizontes T2, T3, ... T10 usando a mesma
coorte de formações completas em T10. Isso impede que cenários longos usem uma
amostra menor que os curtos. A simulação para de apostar no primeiro acerto,
embora a coleta bruta continue até T10.

Os endpoints aceitam `payout_mode=table_base`, que usa `30x` para as mesas Mega
conhecidas e `36x` para as demais. O cálculo usa a quantidade real de alvos e
ordena os fluxos de caixa pelo horário das tentativas, incluindo exposições
simultâneas de formações sobrepostas.

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

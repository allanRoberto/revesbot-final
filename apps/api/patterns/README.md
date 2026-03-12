# Pattern Repository (API)

Este diretório guarda os padrões usados pelo `PatternEngine` do back-end.

## Estrutura

- `definitions/*.json`: metadados de cada padrão
- `engine.py`: avaliação dos padrões via `evaluator`
- `final_suggestion.py`: fusão final (base + otimizado) usada por `/final-suggestion`
- `evaluators/*.py`: um wrapper por evaluator (fonte canônica de registro dos avaliadores)
- compatibilidade: `api/services/pattern_engine.py` e `api/services/final_suggestion_frontend.py` agora são wrappers

## Campos do JSON

- `id`: identificador único do padrão
- `name`: nome amigável
- `version`: versão do padrão
- `kind`: `positive` (padrão de sugestão) ou `negative` (padrão de veto/penalidade)
- `active`: habilita/desabilita sem apagar arquivo
- `priority`: ordem de avaliação (maior primeiro)
- `weight`: peso global na agregação
- `evaluator`: nome do avaliador registrado no engine
- `max_numbers`: limite de números sugeridos por esse padrão
- `params`: parâmetros específicos da regra

Exemplo de parâmetro dinâmico:
- `wait_from_target_sum`: quando `true`, a quantidade de giros aguardados após o gatilho é o alvo calculado pela soma dos dígitos dos 2 números do gatilho.
- `suggestion_cap`: limite máximo final de números quando o padrão negativo estiver ativo.
- `enforce_presence`: quando `true` em padrão positivo, garante presença mínima de números desse padrão no resultado final.
- `min_keep`: quantidade mínima de números preservados para padrões com `enforce_presence`.
- `adaptive.enabled`: ativa calibração automática do peso do padrão por performance recente.
- `adaptive.lookahead`: quantidade de giros para considerar hit no backtest interno.
- `adaptive.window`: quantidade de giros usados na calibração.
- `adaptive.min_signals`: mínimo de sinais para aplicar ajuste pleno.
- `adaptive.min_multiplier`/`adaptive.max_multiplier`: faixa de multiplicador do peso base.

## Como adicionar um novo padrão

1. Crie um arquivo em `api/patterns/definitions/novo_padrao.json`.
2. Registre um novo avaliador em `api/patterns/engine.py`.
3. Crie `api/patterns/evaluators/<nome_do_evaluator>.py` com `evaluate(...)`.
4. Adicione o módulo no registry de `api/patterns/evaluators/__init__.py`.
5. Retorne no avaliador:
- `numbers`: lista de números sugeridos
- `scores` (opcional): score por número
- `explanation`: texto resumido para debug/observabilidade

## Endpoint

- `POST /api/patterns/optimized-suggestion`
- `POST /api/patterns/metrics/backtest`
- `POST /api/patterns/metrics/apply-multipliers`
- `GET /api/patterns/metrics/events`
- payload:

```json
{
  "history": [17, 27, 5, 21],
  "focus_number": 17,
  "from_index": 0,
  "max_numbers": 12
}
```

Resposta inclui:
- `confidence`: confiança final mesclada
- `confidence_breakdown`: separa `api_raw`, `legacy`, `merged`
- `number_details`: diagnóstico por número (`net_score`, `positive_score`, `negative_score`, padrões que apoiam e vetam)
- `adaptive_weights`: auditoria da calibração por padrão (`signals`, `hits`, `hit_rate`, `multiplier`)

## Telemetria e Calibração

### Backtest

`POST /api/patterns/metrics/backtest`

Payload:

```json
{
  "history": [17, 27, 5, 21, 14],
  "max_numbers": 12,
  "max_attempts": 12,
  "max_entries": 500,
  "persist_events": true,
  "use_adaptive_weights": false
}
```

Retorna:
- `summary.totals`: total de eventos/hits/misses/pending
- `summary.patterns`: performance por padrão com `hit_rate` e `recommended_multiplier`
- `confidence_calibration`: taxa de acerto por faixa de confiança (0-9, 10-19, ...)

### Eventos

`GET /api/patterns/metrics/events?limit=500`

Retorna:
- eventos recentes (`events`)
- resumo agregado (`summary`) para leitura rápida de performance

### Auto-tuning de pesos

`POST /api/patterns/metrics/apply-multipliers`

Payload:

```json
{
  "history": [17, 27, 5, 21, 14],
  "max_numbers": 12,
  "max_attempts": 12,
  "max_entries": 500,
  "use_adaptive_weights": false,
  "min_signals": 20,
  "blend": 0.7,
  "dry_run": false
}
```

Retorna:
- `updated`: padrões com `old_weight`, `new_weight`, `recommended_multiplier`
- `skipped`: padrões ignorados com motivo

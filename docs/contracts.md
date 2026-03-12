# Contratos Internos do Sistema

## Legenda de Evidência
- `✅ Confirmado no código`: encontrado diretamente nos arquivos.
- `🔎 Inferido pelo fluxo`: conclusão arquitetural derivada da integração entre módulos.
- `❓ Incerto`: depende de ambiente/gateway/execução não totalmente verificável no repositório.

## 1) Contratos HTTP Internos

### 1.1 Tabela Resumo
| Contrato | Produtor | Consumidor | Evidência | Arquivos principais |
|---|---|---|---|---|
| `POST /api/bet` | `apps/monitoring` | `apps/bot_automatico` | `✅` | `apps/monitoring/src/processor_monitoring.py`, `apps/bot_automatico/main.js` |
| `POST /api/auth/login` | `apps/bot_automatico` | `apps/auth_api` | `✅` (contrato estabilizado com compatibilidade `/` e `/api`) | `apps/bot_automatico/main.js`, `apps/auth_api/main.ts`, `apps/auth_api/routes/index.ts` |
| `GET /api/start-game/:gameId` | `apps/bot_automatico` | `apps/auth_api` | `✅` (contrato estabilizado com compatibilidade `/` e `/api`) | `apps/bot_automatico/main.js`, `apps/auth_api/main.ts`, `apps/auth_api/routes/index.ts` |
| `GET /history/{slug}` | `apps/signals` | `apps/api` | `✅` | `apps/signals/core/api.py`, `apps/api/routes/roulette_history.py` |
| `GET /history-detailed/{slug}` | `apps/signals` | `apps/api` | `✅` | `apps/signals/core/api.py`, `apps/api/routes/roulette_history.py` |
| `POST /api/patterns/final-suggestion` | `apps/signals` | `apps/api` | `✅` | `apps/signals/patterns/api.py`, `apps/api/routes/patterns.py` |

### 1.2 Contrato: `monitoring -> bot_automatico` (`POST /api/bet`)
- Produtor: `apps/monitoring` (`_do_send_single_bet`, `_do_send_bet_to_auto_bot`, `_place_bet_via_api`)
- Consumidor: `apps/bot_automatico` (`app.post("/api/bet", ...)`)
- Evidência: `✅ Confirmado no código`
- Arquivos:
  - `apps/monitoring/src/processor_monitoring.py`
  - `apps/bot_automatico/main.js`

Request payload (observado):
- Obrigatórios no consumidor:
  - `bets`
  - `roulette_url`
  - `gales`
- Opcionais/variantes usadas no produtor:
  - `gale`
  - `valor`
  - `signal_id`
  - `attempts`

Response payload (observado):
- Sucesso:
  - `{ success: true, result: "win"|"loss", attempts, winningNumber?, message? }`
- Erro de validação de mesa:
  - `{ success: true, result: "error", errorCode, errorMessage }`
- Mesa indisponível:
  - `{ success: false, status: "table_offline"|"table_reconnecting", ... }` (HTTP 503)

Risco de quebra:
- `🔎` Contrato aceita múltiplas variantes de payload; campos opcionais não formalizados.

### 1.3 Contrato: `bot_automatico -> auth_api` (`POST /api/auth/login`)
- Produtor: `apps/bot_automatico` (`loginAndGetToken`)
- Consumidor: `apps/auth_api`
- Evidência:
  - `✅` chamada no bot
  - `✅` auth_api aceita `/auth/login` e `/api/auth/login` usando o mesmo router
  - `✅` cookie `bookmaker_token` passou a ser setado sempre quando há token
- Arquivos:
  - `apps/bot_automatico/main.js`
  - `apps/auth_api/main.ts`
  - `apps/auth_api/routes/index.ts`

Request payload:
- Obrigatórios:
  - `email`
  - `password`

Resposta esperada pelo bot:
- Obrigatório implícito:
  - header `set-cookie` contendo `bookmaker_token`

Resposta real no auth_api:
- Login válido:
  - seta cookie `bookmaker_token`
  - retorna JSON com `token` no nível raiz e `isConnected`
- Quando legitimuz está disponível:
  - inclui também `legitimuzStatus`

Risco de quebra:
- `🔎` Baixo após estabilização; permanece dependência de cookie no bot por design atual.

### 1.4 Contrato: `bot_automatico -> auth_api` (`GET /api/start-game/:gameId`)
- Produtor: `apps/bot_automatico` (`getGameWebSocketUrl`)
- Consumidor: `apps/auth_api`
- Evidência:
  - `✅` chamada no bot
  - `✅` auth_api aceita `/start-game/:gameId` e `/api/start-game/:gameId` via mesmo router
- Arquivos:
  - `apps/bot_automatico/main.js`
  - `apps/auth_api/main.ts`
  - `apps/auth_api/routes/index.ts`

Request:
- Obrigatório:
  - `Cookie: bookmaker_token=...`
  - `gameId` em path

Response:
- Bot exige:
  - `success === true`
  - `link` (usa Puppeteer local para extrair WS URL)
- Auth API retorna:
  - `{ success, link, urlGame, cookies, message }`

Risco de quebra:
- `🔎` Baixo após estabilização; depende de cookie válido de login.

### 1.5 Contrato: `signals -> api` (Histórico)
- Produtor: `apps/signals` (`RouletteAPI.api`)
- Consumidor: `apps/api` (`/history` e `/history-detailed`)
- Evidência: `✅ Confirmado no código`
- Arquivos:
  - `apps/signals/core/api.py`
  - `apps/api/routes/roulette_history.py`

Requests:
- `GET /history/{slug}?limit={n}`
- `GET /history-detailed/{slug}?limit={n}` (quando `full_results=True`)

Response aceita no signals:
- Formato 1: lista crua
- Formato 2: objeto com `results` lista

Risco de quebra:
- `🔎` Contrato é tolerante em formato, mas não formalizado por versão/schema.

### 1.6 Contrato: `signals -> api` (Sugestão final)
- Produtor: `apps/signals/patterns/api.py`
- Consumidor: `apps/api/routes/patterns.py`
- Evidência: `✅ Confirmado no código`
- Arquivos:
  - `apps/signals/patterns/api.py`
  - `apps/api/routes/patterns.py`

Request payload:
- Obrigatórios:
  - `history` (lista)
  - `focus_number` (int)
  - `from_index` (int)
  - `max_numbers` (int)

Response usada no signals:
- Obrigatórios práticos:
  - `available` (bool)
  - `suggestion` (lista) ou `list` (lista)
- Opcionais:
  - `confidence` (`score`, `label`) e outros campos de breakdown

Risco de quebra:
- `🔎` Dupla chave (`suggestion`/`list`) aumenta ambiguidade contratual.

## 2) Contratos Redis

### 2.1 Tabela Resumo
| Contrato Redis | Produtor(es) | Consumidor(es) | Evidência | Arquivos principais |
|---|---|---|---|---|
| `pubsub:new_result` | `collector` | `signals`, `monitoring`, `api/ws` | `✅` | `apps/collector/collector_ws_*.py`, `apps/signals/main.py`, `apps/monitoring/src/signal_listener.py`, `apps/api/routes/websocket_signals.py` |
| `pubsub:new_result_simulate` | `signals/simulate.py` | `signals`, `monitoring` | `✅` | `apps/signals/simulate.py`, `apps/signals/main.py`, `apps/monitoring/src/config.py` |
| `streams:signals:new` | `signals` (e `monitoring` para child) | `monitoring`, `api/ws/signals` | `✅` | `apps/signals/core/redis.py`, `apps/monitoring/core/redis.py`, `apps/monitoring/src/signal_listener.py`, `apps/api/routes/websocket_signals.py` |
| `streams:signals:updates` | `monitoring` | `api/ws/signals` | `✅` | `apps/monitoring/src/processor_monitoring.py`, `apps/api/routes/websocket_signals.py` |
| `signal:{id}` | `signals`/`monitoring` | `monitoring`, `api` | `✅` | `apps/signals/core/redis.py`, `apps/monitoring/src/processor_monitoring.py`, `apps/api/routes/signals.py` |
| `signals:active` | `signals`/`monitoring` | `signals`, `api` | `✅` | `apps/signals/core/redis.py`, `apps/monitoring/src/processor_monitoring.py`, `apps/signals/patterns/run_all_patterns.py`, `apps/api/routes/signals.py` |
| `signals:index:triggers` | `signals`/`monitoring` | `signals`/`monitoring` (dedupe) | `✅` | `apps/signals/core/redis.py`, `apps/monitoring/core/redis.py` |

### 2.2 Contrato: `pubsub:new_result`
- Produtor:
  - `apps/collector/collector_ws_evolution.py`
  - `apps/collector/collector_ws_miguel.py`
  - `apps/collector/collector_ws_ezugi.py`
  - `❓` `collector_ws_pragmatic.py` contém publish comentado
- Consumidor:
  - `apps/signals/main.py`
  - `apps/monitoring/src/signal_listener.py`
  - `apps/api/routes/websocket_signals.py` (repasse para websocket client)
- Evidência: `✅` (com ressalva pragmatic)

Payload:
- Obrigatórios (consumo principal):
  - `slug`
  - `result`
- Opcionais:
  - `full_result`

Risco de quebra:
- `✅` Divergência de payload entre produtores (alguns sem `full_result`).

### 2.3 Contrato: `pubsub:new_result_simulate`
- Produtor:
  - `apps/signals/simulate.py`
- Consumidor:
  - `apps/signals/main.py` (modo simulador)
  - `apps/monitoring` (quando `RESULT_CHANNEL` aponta para simulado)
- Evidência: `✅`

Payload:
- Obrigatórios:
  - `slug`
  - `result`
- Opcionais:
  - `full_result`

Risco:
- `🔎` Dependência de env (`SIMULATOR`, `RESULT_CHANNEL`) para consistência do fluxo.

### 2.4 Contrato: `streams:signals:new`
- Produtor:
  - `apps/signals/core/redis.py::save_signal`
  - `apps/monitoring/core/redis.py::save_signal` (criação de child)
- Consumidor:
  - `apps/monitoring/src/signal_listener.py` (xreadgroup)
  - `apps/api/routes/websocket_signals.py` (xread para UI)
- Evidência: `✅`

Envelope do stream:
- Obrigatórios:
  - `signal_id`
  - `data` (JSON string)

`data` (payload de sinal):
- Obrigatórios práticos para monitoring:
  - `id`
  - `triggers`
  - `status`
- Campos frequentemente esperados:
  - `roulette_id`, `bets`, `targets`, `history`, `gales`, `temp_state`, etc.

Risco:
- `✅` Sem versionamento de schema.
- `🔎` Diferença entre implementação `save_signal` de `signals` e `monitoring` (campos/tamanhos defaults) pode gerar variações.

### 2.5 Contrato: `streams:signals:updates`
- Produtor:
  - `apps/monitoring/src/processor_monitoring.py::_persist_and_publish`
- Consumidor:
  - `apps/api/routes/websocket_signals.py`
- Evidência: `✅`

Envelope:
- Obrigatórios:
  - `signal_id`
  - `status`
  - `data` (JSON string)

`data`:
- Snapshot do estado do sinal atualizado.

Risco:
- `🔎` API websocket usa majoritariamente `data`; sem contrato rígido para `status` adicional.

### 2.6 Contrato: Keys (`signal:{id}`, `signals:active`, `signals:index:triggers`)
- `signal:{id}`:
  - Criado via `LPUSH/LTRIM`, atualizado via `LSET` (posição 0).
- `signals:active`:
  - Hash `id -> payload`.
- `signals:index:triggers`:
  - Hash `assinatura -> id` para dedupe.

Evidência: `✅ Confirmado`

Riscos:
- `✅` API remove `signals:*` mas lista `signal:*` (limpeza parcial possível).
- `🔎` Dedupe depende de assinatura implícita e status string.

## 3) Campos Obrigatórios/Opcionais (Matriz Rápida)

| Contrato | Obrigatórios | Opcionais / Variáveis |
|---|---|---|
| `POST /api/bet` | `bets`, `roulette_url`, `gales` | `gale`, `valor`, `signal_id`, `attempts` |
| `POST /api/auth/login` | `email`, `password` | corpo pode incluir outros campos no futuro |
| `GET /api/start-game/:gameId` | `gameId`, cookie `bookmaker_token` | `urlGame`, `cookies`, `message` na resposta |
| `pubsub:new_result` | `slug`, `result` | `full_result` |
| `pubsub:new_result_simulate` | `slug`, `result` | `full_result` |
| `streams:signals:new` | `signal_id`, `data` | campos internos de `data` variam por produtor |
| `streams:signals:updates` | `signal_id`, `status`, `data` | campos internos de `data` variam por status |

## 4) Inconsistências Críticas (Status Atual)

### 4.1 Inconsistência de rota entre `bot_automatico` e `auth_api` (Mitigada)
- Bot chama `/api/auth/login` e `/api/start-game/:id`.
- Auth API agora aceita também os paths com prefixo `/api`, sem remover os paths antigos.
- Evidência: `✅ Confirmado no código`.

### 4.2 Dependência frágil de cookie no login (Mitigada)
- Bot extrai apenas `set-cookie` (`bookmaker_token`).
- Auth API agora seta cookie sempre quando há token e mantém `token` no body para compatibilidade.
- Evidência: `✅ Confirmado no código`.

### 4.3 Ausência de versionamento nos eventos Redis
- Eventos pubsub/streams não têm `schema_version`.
- Evidência: `✅ Confirmado no código`.

### 4.4 Divergência de payload em `new_result`
- Produtores reais publicam majoritariamente `{slug,result}`.
- Simulador inclui `full_result`.
- Evidência: `✅ Confirmado no código`.

### 4.5 Publish comentado em `collector_ws_pragmatic.py`
- Trecho `publish("new_result", ...)` está comentado.
- Evidência: `✅ Confirmado no código`.

### 4.6 Inconsistência entre `signals:*` e `signal:*` na API
- `DELETE /signals` apaga `signals:*`.
- `GET /signals` lista `signal:*`.
- Evidência: `✅ Confirmado no código`.

## 5) Contratos Frágeis (Prioridade de Atenção)
1. Dependência de cookie no `bot_automatico` permanece implícita (apesar de mitigada no `auth_api`).
2. `new_result` sem schema formal e com variantes.
3. `streams:signals:new` dependente de payload JSON não versionado.
4. Ciclo de limpeza/listagem de chaves de sinal com padrões divergentes.

## 6) Recomendações Futuras (Sem Aplicar Nesta Etapa)
1. Definir contrato versionado para eventos Redis (`event_type`, `schema_version`, campos mínimos).
2. Formalizar contrato HTTP interno `monitoring -> bot` e `bot -> auth` em especificação única.
3. Opcional: adaptar bot para fallback explícito por body (`token`) além de cookie.
4. Alinhar padrões de chave (`signal:*` vs `signals:*`) e política de cleanup.
5. Explicitar no runtime quais produtores publicam `new_result` por provedor e cobrir Pragmatic.

# Arquitetura Operacional do Sistema

## Legenda de Evidência
- `✅ Confirmado no código`: comportamento observado diretamente nos arquivos do projeto.
- `🔎 Inferido pelo fluxo atual`: conclusão arquitetural derivada da combinação de módulos e chamadas.
- `❓ Incerto (validação manual)`: ponto que depende de ambiente, deploy, ou scripts não canônicos.

## 1) Visão Geral
Fluxo operacional principal identificado:

`collector -> Redis (pubsub:new_result) -> signals -> Redis (streams:signals:new) -> monitoring -> Redis (streams:signals:updates) -> api (ws/signals)`

Fluxo de execução de aposta:

`monitoring -> bot_automatico (/api/bet) -> auth_api (/auth/login, /start-game) -> provedores externos`

Classificação:
- `✅` Há publicação/consumo de `new_result` e uso de streams de sinais.
- `🔎` O fluxo completo acima representa o caminho principal de produção.
- `❓` Parte de scripts auxiliares/legados pode implementar variações paralelas.

## 2) Aplicações (Mapa por App)

| App | Tipo | Entrypoint | Entrada principal | Saída principal | Redis | Banco | Auth/Sessão |
|---|---|---|---|---|---|---|---|
| `apps/api` | HTTP API (FastAPI) | `start.py -> api.main:app` | HTTP requests + Redis stream/pubsub | JSON/HTML/WebSocket para clientes | consome `new_result`, `streams:signals:*` | lê `history`; lê/escreve `agent_sessions` e `agent_templates` | não depende de auth da casa |
| `apps/collector` | Worker contínuo | `main.py` | WebSockets/APIs de provedores de roleta | grava Mongo + publica `new_result` | publica `new_result` | escreve `history` | não |
| `apps/signals` | Worker contínuo | `main.py` | Redis `new_result`/`new_result_simulate` + HTTP da API (`/history`) | cria sinais em Redis (stream/hash/list) | consome pubsub; publica stream/keys de sinais | sem uso direto no fluxo principal | não |
| `apps/monitoring` | Worker contínuo | `main.py -> src.signal_listener` | Redis streams + canal de resultado | atualiza estado de sinal + chama bot | consome `streams:signals:new` + pubsub resultado; publica `streams:signals:updates` e `signals:active` | sem uso direto no fluxo principal | não |
| `apps/auth_api` | HTTP API (Express/TS) | `main.ts` (`dist/main.js` em prod) | HTTP login/start-game | cookies/token + URL de jogo/WS | não identificado no runtime principal | não | sim (sessão com casa de aposta) |
| `apps/bot_automatico` | Executor + HTTP API | `main.js` | HTTP `/api/bet` + WS das mesas + auth API | execução de aposta em mesa + health/status | não no `main.js` atual | não | sim (depende do `auth_api`/serviço auth) |

Classificação geral:
- `✅` Tipos e entrypoints em `infra/pm2/ecosystem.config.js`.
- `✅` Papéis observados nos módulos `main.py/main.js/main.ts`.
- `🔎` Classificação “fluxo principal” considera apenas entrypoints canônicos do PM2.

## 3) Relações Entre Apps

1. `collector -> signals`
- `✅` Collector publica `new_result` (ex.: `collector_ws_evolution.py`, `collector_ws_miguel.py`, `collector_ws_ezugi.py`).
- `✅` Signals assina canal (`apps/signals/main.py`).

2. `signals -> monitoring`
- `✅` Signals cria sinais em `streams:signals:new` e estruturas `signals:*` (`apps/signals/core/redis.py`).
- `✅` Monitoring consome stream via consumer group (`apps/monitoring/src/signal_listener.py`).

3. `monitoring -> bot_automatico`
- `✅` Monitoring envia HTTP POST para `BET_API_URL` (default `http://localhost:3000/api/bet`) em `apps/monitoring/src/processor_monitoring.py`.
- `✅` Bot expõe `POST /api/bet` (`apps/bot_automatico/main.js`).

4. `bot_automatico -> auth_api`
- `✅` Bot chama login/start-game via `AUTH_BASE_URL` (`apps/bot_automatico/main.js`).
- `✅` Auth API expõe endpoints de login/start-game (`apps/auth_api/routes/index.ts`).

5. `signals -> api`
- `✅` Signals chama endpoints HTTP da API para histórico (`apps/signals/core/api.py` e `apps/signals/patterns/api.py`).

## 4) Redis (Fluxo, Contratos e Diferença PubSub vs Streams)

### 4.1 Canais, Streams e Keys Encontrados
- Pub/Sub:
  - `new_result`
  - `new_result_simulate`
  - `signal_update` (configurado; sem uso forte no fluxo principal)
- Streams:
  - `streams:signals:new`
  - `streams:signals:updates`
- Hash/List/Keys:
  - `signals:active`
  - `signals:index:triggers`
  - `signal:{id}` (acessado também por padrão `signal:*`)
- Consumer Group:
  - `signal_processors`

### 4.2 Diferença Atual entre PubSub e Streams
- `✅` PubSub é usado para resultados de roleta (`new_result`), eventos efêmeros.
- `✅` Streams são usados para ciclo de vida de sinais (`new`/`updates`) com consumo por grupo e ACK.
- `🔎` A arquitetura atual combina os dois modelos: baixa latência no resultado (pubsub) e rastreabilidade/reprocessamento no estado de sinais (streams).

### 4.3 Contratos Redis Implícitos (Sem Versionamento)
- `✅` Payload de `new_result` esperado com pelo menos `{slug, result}`; em alguns pontos existe `full_result`.
- `✅` Payload dos streams usa campo `data` com JSON stringificado.
- `✅` Não há campo de versão de schema (`schema_version`, `event_type_version`, etc.) padronizado nos contratos de runtime.
- `🔎` Mudança de chave/campo pode quebrar consumidores silenciosamente (ex.: monitoring/api ws).

## 5) Banco de Dados

### 5.1 MongoDB
- `apps/collector`
  - `✅` escreve em `roleta_db.history`.
- `apps/api`
  - `✅` lê `history` (rotas de histórico/análise).
  - `✅` lê/escreve `agent_sessions` e `agent_templates`.
  - `✅` coleção `predictions_normalized` está definida no core, sem uso claro no runtime principal.
- `apps/signals` e `apps/monitoring`
  - `✅` no fluxo principal de entrypoint, operam via Redis/API; não foi identificado uso direto de banco.

## 6) Contratos HTTP Internos Relevantes

### 6.1 `signals -> api`
- `✅` `GET /history/{slug}?limit=...`
- `✅` `POST /api/patterns/final-suggestion` (padrão `patterns/api.py`)

### 6.2 `monitoring -> bot_automatico`
- `✅` `POST /api/bet`
- `✅` Payload observado inclui campos como `bets`, `roulette_url`, `gale`/`gales`, `valor`, `signal_id`.

### 6.3 `bot_automatico -> auth_api` (Ponto Crítico)
- `✅` Bot usa:
  - `/api/auth/login`
  - `/api/start-game/:gameId`
- `✅` Auth API local expõe:
  - `/auth/login`
  - `/start-game/:gameId`
- `🔎` Inconsistência de contrato local entre paths (prefixo `/api` no bot vs rotas sem `/api` no auth_api local).
- `❓` Pode funcionar em produção se `AUTH_BASE_URL` apontar para outro serviço/gateway com reescrita de rota.

## 7) Dependências Externas
- `apps/collector`
  - `✅` conexões com provedores externos de mesa (Pragmatic, Evolution/vaidebet, Ezugi, endpoint Miguel).
- `apps/auth_api`
  - `✅` integração com APIs da casa de aposta (`lotogreen.bet.br`) e Puppeteer para extrair URL de WS.
- `apps/bot_automatico`
  - `✅` usa WebSocket da mesa obtido via fluxo de start-game/auth.
- `apps/api`
  - `✅` módulo de agent suporta provedores LLM (`openai` e opcional `anthropic`).

## 8) Variáveis de Ambiente Relevantes por App

### 8.1 `apps/api`
- `REDIS_CONNECT`, `mongo_url`, `PORT`
- `LLM_PROVIDER`, `LLM_MODELS`, `LLM_PRICING`

### 8.2 `apps/collector`
- `MONGO_URL`, `REDIS_CONNECT`, `PORT` (dummy/health local)

### 8.3 `apps/signals`
- `REDIS_CONNECT`, `BASE_URL_API`, `SIMULATOR`, `RESULT_CHANNEL`, `SIM_CHANNEL`, `SIM_DELAY`

### 8.4 `apps/monitoring`
- `REDIS_CONNECT`, `RESULT_CHANNEL`, `UPDATE_CHANNEL`
- `BET_API_URL`
- `MONITORING_ASSERTIVITY_*`, `DEFAULT_BET_VALUE`, `METRICS_PORT`

### 8.5 `apps/auth_api`
- `PORT`

### 8.6 `apps/bot_automatico`
- `AUTH_BASE_URL`, `API_PORT`, `DEBUG_MODE`

Classificação:
- `✅` Variáveis acima aparecem nos entrypoints e módulos de runtime principal.
- `🔎` Existem muitas variáveis em scripts auxiliares/legados fora do caminho PM2 principal.

## 9) Portas e Runtime
- `✅` PM2 atual:
  - `api` -> `PORT=8080`
  - `auth_api` -> `3090` (default no app)
  - `bot_automatico` -> `API_PORT=3000` (default no app)
  - `collector/signals/monitoring` como workers sem API pública primária
- `✅` `collector` possui código de dummy HTTP server, mas não é iniciado no `main.py` atual.
- `❓` `METRICS_PORT` no monitoring está configurado, porém não há servidor de métricas explícito no entrypoint atual.

## 10) Pontos Frágeis e Pendências Arquiteturais (Destaques)

### 10.1 Inconsistência de contrato `bot_automatico` x `auth_api`
- Status: `✅ Confirmado no código` + `🔎 risco operacional`.
- Impacto: falha de autenticação/start-game quando `AUTH_BASE_URL` aponta para o `auth_api` local sem gateway de reescrita.

### 10.2 Contratos Redis implícitos e não versionados
- Status: `✅ Confirmado`.
- Impacto: evolução de payload com risco de quebra cruzada (`signals`, `monitoring`, `api/ws`).

### 10.3 Uso híbrido de PubSub e Streams
- Status: `✅ Confirmado`.
- Impacto: aumenta flexibilidade, mas exige clareza de fronteira (evento efêmero vs estado rastreável) e observabilidade consistente.

### 10.4 Credenciais/segredos hardcoded
- Status: `✅ Confirmado no código`.
- Evidência: presença de credenciais/tokens/URLs sensíveis em alguns módulos de collector/bot.
- Impacto: risco de vazamento, rotação difícil e comportamento inconsistente entre ambientes.

### 10.5 Divergência PM2 vs exemplo Nginx
- Status: `✅ Confirmado`.
- Evidência:
  - PM2 roda API em `8080` (`infra/pm2/ecosystem.config.js`)
  - exemplo de Nginx aponta `/api/` para `127.0.0.1:8000` (`infra/nginx/revesbot.conf.example`)
- Impacto: roteamento incorreto em deploy se arquivo exemplo for aplicado sem ajuste.

## 11) Áreas Mais Maduras vs Áreas a Evoluir

### 11.1 Mais maduras
- `✅` Estrutura de apps consolidada e entrypoints canônicos definidos via PM2.
- `✅` Pipeline de sinais com separação clara: geração (`signals`) e ciclo de vida (`monitoring`).

### 11.2 A evoluir
- `🔎` Contratos internos HTTP/Redis formalizados (schemas/versionamento).
- `🔎` Gestão de segredos e hardening operacional.
- `🔎` Redução de ambiguidade causada por scripts legados fora do caminho principal.

## 12) Itens Incertos que Precisam Validação Manual
1. `❓` Qual endpoint real de `AUTH_BASE_URL` em produção (serviço local vs gateway externo com `/api`).
2. `❓` Se o provider Pragmatic no collector deve publicar em Redis (trecho comentado).
3. `❓` Se `METRICS_PORT` em monitoring está previsto para etapa futura ou há endpoint externo não versionado no repositório.
4. `❓` Quais scripts alternativos em `signals`/`bot_automatico` ainda são usados operacionalmente fora do PM2 padrão.

## 13) Recomendações Futuras (Sem Aplicar Nesta Etapa)
1. Definir contratos de evento versionados para Redis (`event_type`, `schema_version`, validação de payload).
2. Formalizar contrato HTTP interno entre `monitoring`, `bot_automatico` e `auth_api` (OpenAPI mínimo ou documento de contrato).
3. Centralizar segredos em variáveis de ambiente/secret manager e remover hardcodes.
4. Alinhar `infra/nginx` ao runtime PM2 efetivo e documentar portas oficiais por ambiente.
5. Criar checklist operacional de observabilidade para pubsub + streams (lag, pending, consumer group health, taxa de erro).

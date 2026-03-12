# Runtime das Aplicações

Este documento consolida o runtime operacional após a reorganização estrutural.

## apps/api
- Nome: `api`
- Função: API HTTP principal (FastAPI)
- Linguagem: Python
- Entrypoint final: `apps/api/start.py`
- Comando local: `cd apps/api && python3 start.py`
- Comando de produção: `cd apps/api && PORT=8080 python3 start.py`
- Comando PM2: `pm2 start infra/pm2/ecosystem.config.js --only api`
- Dependências relevantes:
  - Redis: `REDIS_CONNECT`
  - MongoDB: `mongo_url` via `.env`
  - Porta HTTP: `PORT` (default 8080)
  - Bot automático (api.html): `BOT_AUTOMATION_ENABLED`, `BOT_API_URL`, `BOT_HEALTH_URL`
  - Métricas de backtest no front (api.html): `PATTERN_METRICS_ENABLED` (default desativado)
- Observações operacionais:
  - `start.py` faz bootstrap de import para `api.main`.
  - Processo é servidor HTTP/API.

## apps/collector
- Nome: `collector`
- Função: coleta resultados de mesas via WebSocket e persiste/publica eventos
- Linguagem: Python
- Entrypoint final: `apps/collector/main.py`
- Comando local: `cd apps/collector && python3 main.py`
- Comando de produção: `cd apps/collector && python3 main.py`
- Comando PM2: `pm2 start infra/pm2/ecosystem.config.js --only collector`
- Dependências relevantes:
  - Redis: `REDIS_CONNECT`
  - MongoDB: `MONGO_URL`
  - Porta HTTP: usa `PORT` para health server dummy (se ativado pelo app)
- Observações operacionais:
  - Processo é worker.
  - Coleta em múltiplas threads (provedores diferentes).

## apps/signals
- Nome: `signals`
- Função: processamento de histórico/resultados e geração de sinais
- Linguagem: Python
- Entrypoint final: `apps/signals/main.py`
- Comando local: `cd apps/signals && python3 main.py`
- Comando de produção: `cd apps/signals && python3 main.py`
- Comando PM2: `pm2 start infra/pm2/ecosystem.config.js --only signals`
- Dependências relevantes:
  - Redis (estado de sinais): `REDIS_SIGNALS_CONNECT` (fallback: `REDIS_CONNECT`)
  - Redis (resultados/pubsub): `REDIS_RESULTS_CONNECT` (fallback: Redis de sinais)
  - API base para histórico: `BASE_URL_API`
  - Canal de resultados: `RESULT_CHANNEL` (default `new_result` / `new_result_simulate`)
- Observações operacionais:
  - Processo é worker assíncrono.
  - Em modo simulador usa `SIMULATOR=true`.

## apps/monitoring
- Nome: `monitoring`
- Função: consumo de sinais ativos e monitoramento de ciclo de vida
- Linguagem: Python
- Entrypoint final: `apps/monitoring/main.py`
- Comando local: `cd apps/monitoring && PYTHONPATH=. python3 main.py`
- Comando de produção: `cd apps/monitoring && PYTHONPATH=. python3 main.py`
- Comando PM2: `pm2 start infra/pm2/ecosystem.config.js --only monitoring`
- Dependências relevantes:
  - Redis (estado de sinais/streams): `REDIS_SIGNALS_CONNECT` (fallback: `REDIS_CONNECT`)
  - Redis (resultados/pubsub): `REDIS_RESULTS_CONNECT` (fallback: Redis de sinais)
  - Canal de resultados: `RESULT_CHANNEL` (default em `src/config.py`)
  - Porta de métricas: `METRICS_PORT` (default 8090)
- Observações operacionais:
  - `main.py` é wrapper mínimo que inicia `src.signal_listener`.
  - Processo é worker (não expõe API HTTP principal).

## apps/auth_api
- Nome: `auth_api`
- Função: API Node/TypeScript para autenticação/sessão e utilidades de start-game
- Linguagem: Node.js + TypeScript
- Entrypoint final:
  - Desenvolvimento: `apps/auth_api/main.ts`
  - Produção: `apps/auth_api/dist/main.js`
- Comando local: `cd apps/auth_api && npm run dev`
- Comando de produção:
  - `cd apps/auth_api && npm run build`
  - `cd apps/auth_api && npm run start`
- Comando PM2: `pm2 start infra/pm2/ecosystem.config.js --only auth_api`
- Dependências relevantes:
  - Porta HTTP: `PORT` (default 3090)
  - Build obrigatório para produção: `dist/main.js`
- Observações operacionais:
  - Scripts padronizados: `dev`, `build`, `start` (`start:src` opcional).
  - Runtime de produção não depende de `tsx`.

## apps/bot_automatico
- Nome: `bot_automatico`
- Função: bot de apostas automáticas e API de operação
- Linguagem: Node.js
- Entrypoint final: `apps/bot_automatico/main.js`
- Comando local: `cd apps/bot_automatico && npm run start`
- Comando de produção: `cd apps/bot_automatico && npm run start`
- Comando PM2: `pm2 start infra/pm2/ecosystem.config.js --only bot_automatico`
- Dependências relevantes:
  - API auth: `AUTH_BASE_URL`
  - Porta HTTP do bot: `API_PORT` (default 3000)
  - Redis: usado por fluxos de automação/streams
- Observações operacionais:
  - Entrypoint padronizado de forma definitiva em `main.js`.

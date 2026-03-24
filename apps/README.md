# Apps

Cada subdiretório em `apps/` representa uma aplicação isolada do monorepo.

- `api/`: FastAPI principal, templates, rotas e backtests.
- `auth_api/`: serviço Node/TypeScript para autenticação e sessão da casa.
- `bot_automatico/`: executor Node.js das apostas automáticas.
- `collector/`: coletores Python de resultados e publicação em Redis.
- `monitoring/`: monitoramento Python de sinais e gatilhos.
- `signals/`: motor Python de padrões e formação de sinais.

Nesta etapa, a prioridade é preservar entrypoints e compatibilidade. Refatorações
internas mais profundas ficam para fases futuras.

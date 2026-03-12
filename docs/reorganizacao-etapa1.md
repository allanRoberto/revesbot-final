# Reorganização Etapa 1 (incremental)

## Objetivo
Organizar o repositório em um monorepo híbrido (Python + JavaScript), sem refatoração destrutiva e preservando compatibilidade.

## Movimentação aplicada
- `src/bot-automatico` -> `apps/bot_automatico`
- `src/bot-automatico/api` -> `apps/auth_api`
- `src/signals` -> `apps/signals`
- `src/monitoring` -> `apps/monitoring`
- `src/collector` -> `apps/collector`

## Compatibilidade legada
Para reduzir ruptura nesta etapa, os caminhos antigos em `src/` foram mantidos como links simbólicos:
- `src/bot-automatico` -> `apps/bot_automatico`
- `src/signals` -> `apps/signals`
- `src/monitoring` -> `apps/monitoring`
- `src/collector` -> `apps/collector`

Além disso:
- `apps/bot_automatico/api` -> `apps/auth_api`

Com isso, comandos legados baseados em `src/...` continuam válidos.

## Shared inicial (priorizando signals)
Foi criada a base `shared/` para centralização futura, com cópia canônica a partir de `apps/signals`:
- `shared/python/roulette/roulettes_list.py`
- `shared/python/redis/redis_client.py`
- `shared/python/utils/*` (utilitários de `signals/helpers/utils`)

Nesta etapa, os apps ainda não foram forçados a consumir `shared/` para evitar quebra.

## Infra inicial
Estrutura criada:
- `infra/pm2/`
- `infra/nginx/`
- `infra/deploy/`

Com templates base para evolução de staging/produção.

## Observações
- `run_all.sh`, `src/monitor_bot.py` e `src/monitor_bot_integrado.py` não foram alterados por decisão explícita.
- Ajuste de path crítico aplicado em `api/services/pattern_engine.py` para priorizar `apps/signals` e manter fallback para `src/signals`.
- `__init__.py` foram adicionados nos diretórios Python relevantes em `apps/signals`, `apps/monitoring` e `apps/collector`.

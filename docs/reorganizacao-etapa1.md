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
Para reduzir ruptura nesta etapa, o root `src/` foi mantido apenas como camada fina de compatibilidade:
- `src/monitor_bot.py`
- `src/monitor_bot_integrado.py`
- `src/README.md`

Além disso:
- o `PatternEngine` da API prioriza `apps/signals/patterns` e mantém fallback para `src/signals/patterns`;
- `apps/monitoring` ainda preserva o pacote interno `src/`, mas os entrypoints principais passaram a aceitar execução tanto a partir do diretório do app quanto do root do repositório;
- `apps/bot_automatico/api` já foi separado como `apps/auth_api`.

Com isso, a compatibilidade foi mantida sem depender de links simbólicos como mecanismo principal.

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
- `run_all.sh`, `src/monitor_bot.py` e `src/monitor_bot_integrado.py` foram preservados como compatibilidade.
- Ajuste de path crítico aplicado em `api/services/pattern_engine.py` para priorizar `apps/signals` e manter fallback para `src/signals`.
- `__init__.py` foram adicionados nos diretórios Python relevantes em `apps/signals`, `apps/monitoring` e `apps/collector`.
- `apps/monitoring` teve imports internos estabilizados para reduzir dependência de `PYTHONPATH=.` e do `cwd` do processo.

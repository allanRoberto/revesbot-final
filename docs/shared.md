# Shared Python Consolidation (Etapa Incremental)

## Escopo desta etapa
Consolidação conservadora de utilitários Python claramente compartilhados, com wrappers compatíveis para preservar imports legados.

## Centralizado agora
1. `graceful.py`
- Fonte canônica: `shared/python/utils/graceful.py`
- Wrappers compatíveis mantidos em:
  - `apps/api/helpers/utils/graceful.py`
  - `apps/collector/helpers/utils/graceful.py`
  - `apps/signals/helpers/utils/graceful.py`
  - `apps/monitoring/helpers/utils/graceful.py`
  - `apps/monitoring/src/helpers/utils/graceful.py`

2. `telegram.py`
- Fonte canônica: `shared/python/utils/telegram.py`
- Wrappers compatíveis mantidos em:
  - `apps/api/helpers/utils/telegram.py`
  - `apps/collector/helpers/utils/telegram.py`
  - `apps/signals/helpers/utils/telegram.py`
  - `apps/monitoring/helpers/utils/telegram.py`
  - `apps/monitoring/src/helpers/utils/telegram.py`

3. `filters.py` (somente onde seguro)
- Base adotada: `shared/python/utils/filters.py` (alinhada à versão de `signals`)
- Aplicado em:
  - `apps/signals/helpers/utils/filters.py` (wrapper para shared)
  - `apps/monitoring/src/helpers/utils/filters.py` (wrapper para shared + `get_figure` preservada localmente no mesmo caminho legado)

4. `get_neighbords.py` (somente onde seguro)
- Base adotada: `shared/python/utils/get_neighbords.py` (alinhada à versão de `signals`)
- Aplicado em:
  - `apps/signals/helpers/utils/get_neighbords.py` (wrapper para shared)
  - `apps/monitoring/helpers/utils/get_neighbords.py` (wrapper para shared)
  - `apps/monitoring/src/helpers/utils/get_neighbords.py` (wrapper para shared)

## Removido nesta etapa
1. `repetition_full.py` (código morto)
- Removidos:
  - `apps/api/helpers/utils/repetition_full.py`
  - `apps/signals/helpers/utils/repetition_full.py`
  - `shared/python/utils/repetition_full.py`
- Motivo: não havia uso real via imports no projeto.

2. `get_url_roulette.py` (arquivo vazio e sem uso)
- Removidos:
  - `apps/api/helpers/utils/get_url_roulette.py`
  - `apps/collector/helpers/utils/get_url_roulette.py`
  - `apps/signals/helpers/utils/get_url_roulette.py`
  - `shared/python/utils/get_url_roulette.py`
- Motivo: arquivos 0 bytes e sem referências de uso.

## Permaneceu local nesta etapa
1. `redis_client.py`
- Mantido local por divergência de runtime:
  - `apps/api` usa `redis.asyncio`
  - `collector`/`monitoring` usam cliente sync

2. `roulettes_list.py`
- Mantido local por divergência semântica de listas entre apps (API, collector, monitoring, signals).

3. `get_mirror.py`
- Mantido local por divergência funcional entre versões (mapeamentos distintos).

4. `tracker.py`
- Mantido local no `monitoring` por divergência funcional em relação à versão de `signals/shared`.

5. `apps/api/helpers/utils/filters.py`
- Mantido local explicitamente nesta etapa, sem alterações.

## Adiado por divergência funcional
- Unificação global de `redis_client.py`
- Unificação global de `roulettes_list.py`
- Unificação global de `get_mirror.py`
- Unificação global de `tracker.py`
- Unificação de variantes de `filters.py` fora de `signals` e do caminho efetivo de `monitoring/src`

## Observações de compatibilidade
- Wrappers preservam caminhos legados de import para evitar ruptura imediata.
- Não houve alteração de regra de negócio; somente redirecionamento de utilitários seguros para `shared/python`.

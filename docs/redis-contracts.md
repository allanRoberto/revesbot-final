# Contratos Redis do Sistema

## Legenda de Evidência
- `✅ Confirmado`: observado diretamente no código.
- `🔎 Inferido`: deduzido do fluxo integrado entre produtores e consumidores.
- `❓ Incerto`: depende de execução externa, scripts legados, ou contexto de deploy não explícito.

## 1) Escopo
Contratos analisados:
1. `pubsub:new_result`
2. `pubsub:new_result_simulate`
3. `streams:signals:new`
4. `streams:signals:updates`
5. `signal:{id}`
6. `signals:active`
7. `signals:index:triggers`

## 2) Matriz de Contratos Redis

| Contrato | Produtor(es) | Consumidor(es) | Evidência | Arquivos |
|---|---|---|---|---|
| `pubsub:new_result` | `collector_ws_evolution.py`, `collector_ws_miguel.py`, `collector_ws_ezugi.py` | `signals/main.py`, `monitoring/src/signal_listener.py`, `api/routes/websocket_signals.py` | `✅` | `apps/collector/collector_ws_evolution.py`, `apps/collector/collector_ws_miguel.py`, `apps/collector/collector_ws_ezugi.py`, `apps/signals/main.py`, `apps/monitoring/src/signal_listener.py`, `apps/api/routes/websocket_signals.py` |
| `pubsub:new_result_simulate` | `signals/simulate.py` | `signals/main.py` (simulador), `monitoring` via `RESULT_CHANNEL` | `✅` + `🔎` | `apps/signals/simulate.py`, `apps/signals/main.py`, `apps/monitoring/src/config.py`, `apps/monitoring/src/signal_listener.py` |
| `streams:signals:new` | `signals/core/redis.py`, `monitoring/core/redis.py` (child) | `monitoring/src/signal_listener.py`, `api/routes/websocket_signals.py` | `✅` | `apps/signals/core/redis.py`, `apps/monitoring/core/redis.py`, `apps/monitoring/src/signal_listener.py`, `apps/api/routes/websocket_signals.py` |
| `streams:signals:updates` | `monitoring/src/processor_monitoring.py` | `api/routes/websocket_signals.py` | `✅` | `apps/monitoring/src/processor_monitoring.py`, `apps/api/routes/websocket_signals.py` |
| `signal:{id}` | `signals/core/redis.py` (cria), `monitoring/src/processor_monitoring.py` (atualiza) | `api/routes/signals.py` | `✅` | `apps/signals/core/redis.py`, `apps/monitoring/src/processor_monitoring.py`, `apps/api/routes/signals.py` |
| `signals:active` | `signals/core/redis.py`, `monitoring/src/processor_monitoring.py` | `signals/patterns/run_all_patterns.py`, `api/routes/signals.py` (delete parcial) | `✅` + `🔎` | `apps/signals/core/redis.py`, `apps/monitoring/src/processor_monitoring.py`, `apps/signals/patterns/run_all_patterns.py`, `apps/api/routes/signals.py` |
| `signals:index:triggers` | `signals/core/redis.py`, `monitoring/core/redis.py` | `signals/core/redis.py`, `monitoring/core/redis.py` | `✅` | `apps/signals/core/redis.py`, `apps/monitoring/core/redis.py` |

## 3) Payload Real por Contrato

### 3.1 `pubsub:new_result`
- Produtor:
  - `collector_ws_evolution.py`, `collector_ws_miguel.py`, `collector_ws_ezugi.py`
- Consumidor:
  - `signals/main.py`
  - `monitoring/src/signal_listener.py`
  - `api/routes/websocket_signals.py`
- Evidência: `✅`

Payload observado:
- Mínimo (dominante):  
  `{"slug": "<roulette_id>", "result": <int>}`
- Enriquecido (não dominante no runtime principal):  
  `{"slug": "...", "result": ..., "full_result": {...}}`

Campos:
- Obrigatórios (consumo atual): `slug`, `result`
- Opcionais: `full_result`
- Implícitos: tipo numérico de `result`, formato textual de `slug`

### 3.2 `pubsub:new_result_simulate`
- Produtor:
  - `signals/simulate.py`
- Consumidor:
  - `signals/main.py` (quando `SIMULATOR=true`)
  - `monitoring` (quando `RESULT_CHANNEL` aponta para canal simulado)
- Evidência: `✅` + `🔎`

Payload observado:
`{"slug":"<roulette_id>", "result": <int>, "full_result": <obj|null>}`

Campos:
- Obrigatórios: `slug`, `result`
- Opcionais: `full_result`

### 3.3 `streams:signals:new`
- Produtor:
  - `signals/core/redis.py::save_signal`
  - `monitoring/core/redis.py::save_signal` (fluxo de child signal)
- Consumidor:
  - `monitoring/src/signal_listener.py` (xreadgroup)
  - `api/routes/websocket_signals.py` (xread)
- Evidência: `✅`

Envelope do stream:
`{ "signal_id": "<uuid>", "data": "<json-string>" }`

`data` (payload de sinal) observado:
- Campos frequentes:
  - `id`, `roulette_id`, `roulette_name`, `roulette_url`
  - `pattern`, `triggers`, `targets`, `bets`
  - `status`, `history`, `snapshot`
  - `gales`, `score`, `attempts`, `message`
  - `created_at`, `updated_at`, `timestamp`
  - `temp_state`, `tags`, `type`

Campos:
- Obrigatórios no envelope: `signal_id`, `data`
- Obrigatórios práticos no consumidor monitoring: `id`, `triggers`, `status` (via validação do model)
- Opcionais: vários campos de telemetria/estado
- Implícitos: `data` deve ser JSON válido; arrays numéricas em `triggers/bets/targets`

### 3.4 `streams:signals:updates`
- Produtor:
  - `monitoring/src/processor_monitoring.py::_persist_and_publish`
- Consumidor:
  - `api/routes/websocket_signals.py`
- Evidência: `✅`

Envelope:
`{ "signal_id": "<uuid>", "status": "<status>", "data": "<json-string>" }`

Campos:
- Obrigatórios no envelope: `signal_id`, `status`, `data`
- Obrigatórios práticos para UI/API: `data` parseável
- Opcionais: campos internos do snapshot variam por status

### 3.5 `signal:{id}`
- Produtor/atualizador:
  - Criação em `signals/core/redis.py` via `LPUSH/LTRIM`
  - Atualização em `monitoring/src/processor_monitoring.py` via `LSET 0`
- Consumidor:
  - `api/routes/signals.py`
- Evidência: `✅`

Estrutura:
- Redis List com snapshot JSON na posição `0`.

Campos:
- Obrigatório implícito para update: lista já existente na chave (`LSET` pressupõe índice 0 válido)

### 3.6 `signals:active`
- Produtor:
  - `signals/core/redis.py` (`HSET`)
  - `monitoring/src/processor_monitoring.py` (`HSET`/`HDEL`)
- Consumidor:
  - `signals/patterns/run_all_patterns.py` (`HGETALL`)
  - `api/routes/signals.py` (limpeza parcial via `signals:*`)
- Evidência: `✅` + `🔎`

Estrutura:
- Hash `signal_id -> payload JSON`

### 3.7 `signals:index:triggers`
- Produtor/consumidor:
  - `signals/core/redis.py`
  - `monitoring/core/redis.py`
- Evidência: `✅`

Estrutura:
- Hash `signature(roulette+pattern+triggers) -> signal_id`

## 4) Divergências Entre Produtores
1. `new_result`:
- produtores reais (collector) enviam majoritariamente payload mínimo
- simulador envia payload enriquecido com `full_result`
- trecho Pragmatic enriquecido está comentado

2. `streams:signals:new`:
- `signals/core/redis.py` e `monitoring/core/redis.py` geram payload semelhante, mas com diferenças de defaults e campos (ex.: tamanho de `history`, `created_at`)

3. `signal:{id}`:
- fluxo de criação e update distribuído em serviços diferentes, com dependência de ordem implícita

## 5) Dependências Implícitas dos Consumidores
1. `signals/main.py`:
- assume `slug` e `result` no pubsub
- usa `full_result` apenas se existir

2. `monitoring/src/signal_listener.py`:
- assume `signal_id` + `data` no stream `signals:new`
- assume `slug` + `result` no canal de resultado

3. `monitoring/src/processor_monitoring.py`:
- assume que `signal:{id}` existe para `LSET`

4. `api/routes/websocket_signals.py`:
- assume campo `data` nos streams e JSON válido

5. `api/routes/signals.py`:
- lista por `signal:*`, mas rotina de limpeza de `/signals` remove `signals:*`

## 6) Riscos Críticos (Destaque)

### 6.1 Ausência de `schema_version`
- Eventos pubsub e streams não carregam versão de contrato.
- Risco: evolução de payload com quebra silenciosa entre apps.

### 6.2 Publish comentado em `collector_ws_pragmatic.py`
- O publish de `new_result` está comentado no provider Pragmatic.
- Risco: assimetria de dados/eventos por provedor.

### 6.3 Dependência de `LSET` em `signal:{id}` já existir
- Monitoring atualiza `signal:{id}` via `LSET` índice 0.
- Risco: se ordem de criação falhar, update quebra.

### 6.4 ACK precoce no monitoring
- ACK em `streams:signals:new` ocorre logo após enfileirar task.
- Risco: perda de mensagem em falhas posteriores de processamento.

### 6.5 Divergência entre `signal:*` e `signals:*`
- API lista `signal:*`, mas delete usa `signals:*`.
- Risco: limpeza parcial e estado residual.

### 6.6 Diferença entre payload mínimo de `new_result` e payload enriquecido do simulador
- Consumidores funcionam hoje com mínimo, mas comportamentos secundários usam `full_result`.
- Risco: features dependentes de enriquecimento não serem acionadas no fluxo real.

## 7) Estratégia Conservadora de Estabilização (Compatível)

### 7.1 Princípios
1. Compatibilidade retroativa total.
2. Mudanças aditivas (sem remover campos atuais).
3. Primeiro fortalecer consumidores, depois enriquecer produtores.

### 7.2 Rollout Recomendado (faseado)
1. **Fase 1 (consumidores primeiro):** aceitar payload antigo + novo nos consumidores.
   - Normalização defensiva:
     - pubsub: garantir `slug/result` com coerção e fallback
     - streams: validar envelope (`signal_id/data/status`) sem quebrar legado
2. **Fase 2 (produtores depois):** adicionar metadados opcionais nos produtores.
   - Ex.: `schema_version`, `event_type`, `source`, `emitted_at`
   - Sem remover payload atual.
3. **Fase 3 (endurecimento gradual):** considerar validação/log mais rígido.
   - logs/alertas para payload fora do contrato canônico
   - eventual rejeição controlada apenas após período de observação

### 7.3 Exemplo de contrato canônico aditivo (não aplicado ainda)
- `new_result`:
  - atual: `{slug, result, full_result?}`
  - aditivo: `{slug, result, full_result?, schema_version?, event_type?, source?, emitted_at?}`
- `streams:signals:new`:
  - envelope atual mantido
  - metadados opcionais no `data` sem remover campos legados

## 8) Endurecimento Implementado nos Consumidores (Março/2026)

Status desta etapa: **aplicado apenas em consumidores**, sem alterar produtores, canais, streams, ACK ou estratégia de `LSET`.

### 8.1 `pubsub:new_result` e `pubsub:new_result_simulate`
- Consumidores endurecidos:
  - `apps/signals/main.py`
  - `apps/monitoring/src/signal_listener.py`
  - `apps/api/routes/websocket_signals.py`
- Evidência: `✅ Confirmado`
- Regras aplicadas:
  - parse defensivo de JSON (`dict` obrigatório)
  - normalização de `slug` com fallback para `roulette_id`
  - normalização de `result` com fallback para `value/number`
  - coerção para `int` **apenas quando segura**:
    - aceita `int` nativo
    - aceita `str` inteira estrita (ex.: `"12"`, `"-3"`)
    - rejeita `bool`, `float`, string não numérica e heurística agressiva
  - payload inválido gera `warning` e é descartado

### 8.2 `streams:signals:new` no monitoring e API WebSocket
- Consumidores endurecidos:
  - `apps/monitoring/src/signal_listener.py`
  - `apps/api/routes/websocket_signals.py`
- Evidência: `✅ Confirmado`
- Regras aplicadas:
  - validação defensiva do envelope (`fields` deve ser `dict`)
  - campo `data` obrigatório e JSON válido
  - `signal_id` obrigatório (com fallback conservador para `data.id`)
  - `status` opcional, mas validado quando presente
  - se `data` for inválido/inconsistente: `warning` com contexto (`message_id`) e descarte
  - não repassa payload parcialmente corrompido ao frontend em `/ws/signals`

### 8.3 Logging e observabilidade
- Implementado log amostrado para evitar flood:
  - primeiras ocorrências sempre logadas
  - depois, amostragem periódica
- Formato de alerta:
  - contrato (`redis:<canal/stream>`)
  - motivo do descarte
  - contexto quando disponível (ex.: `message_id`)

### 8.4 Itens explicitamente não alterados nesta fase
- produtores Redis (`collector`, `signals/simulate`, persistência de updates)
- contrato de payload no produtor (sem `schema_version` ainda)
- divergência estrutural `signal:*` vs `signals:*`

### 8.5 `signal:{id}` update hardened
- Implementado em:
  - `apps/monitoring/src/processor_monitoring.py`
- Evidência: `✅ Confirmado`
- Endurecimento aplicado:
  - update continua priorizando `LSET key 0 payload` (comportamento original).
  - fallback para `LPUSH + LTRIM 0 0` **somente** quando o erro do `LSET` é claramente:
    - chave inexistente (`no such key`)
    - índice fora do range (`index out of range`)
  - warning de fallback com contexto operacional:
    - `signal_id`
    - `key`
    - operação original (`LSET`)
    - motivo do fallback (erro Redis)
  - erros inesperados (incluindo `WRONGTYPE`/tipo inválido de key) são logados e **propagados**.
- Compatibilidade:
  - mantém `signal:{id}` como `list`
  - mantém payload e leitura da API (`LRANGE`) sem mudança de contrato

### 8.6 `streams:signals:new` ACK hardened
- Implementado em:
  - `apps/monitoring/src/signal_listener.py`
  - `apps/monitoring/src/processor_monitoring.py`
- Evidência: `✅ Confirmado`
- Endurecimento aplicado:
  - ACK deixou de ocorrer logo após criação de task.
  - ACK agora ocorre apenas após confirmação de startup essencial do worker:
    - validação de modelo (`Signal.model_validate`)
    - entrada segura no loop de monitoramento por fila (`monitor_single_signal_queue`)
- ACK imediato mantido apenas para casos claramente não recuperáveis:
  - envelope/data inválidos
  - `signal_id` já monitorado
  - falha definitiva de validação de modelo (payload incompatível)
- Em falha inesperada (potencialmente transitória), o listener **não ACKa**:
  - mensagem permanece pendente para recuperação/reprocessamento operacional
  - log explícito com contexto: `signal_id`, `message_id`, `motivo`
- Compatibilidade:
  - sem mudança de producer, stream, consumer group ou payload
  - sem mudança de regras de negócio do monitoring

Observação operacional:
- O endurecimento reduz risco de perda silenciosa por ACK precoce, mas pode aumentar volume de pendentes quando houver falhas inesperadas repetidas.

### 8.7 `signal:{id}` vs `signals:*` (papel e inconsistência de limpeza)
- Evidência: `✅ Confirmado`
- Escopo analisado:
  - `apps/signals/core/redis.py`
  - `apps/monitoring/core/redis.py`
  - `apps/monitoring/src/processor_monitoring.py`
  - `apps/api/routes/signals.py`
  - `apps/monitoring/clear_signals.sh`

Papel funcional de cada key:
- `signal:{id}`:
  - snapshot por sinal (estrutura `list`, head no índice `0`)
  - escrita/criação em `signals/core/redis.py` e `monitoring/core/redis.py`
  - update em `monitoring/src/processor_monitoring.py`
  - leitura na API (`GET /signals`) via `signal:*`
- `signals:active`:
  - índice hash de sinais ativos (`signal_id -> payload`)
  - usado por monitoring para ciclo de vida ativo/finalizado
  - lido por signals em fluxos de controle/dedupe
- `signals:index:triggers`:
  - índice hash de dedupe por assinatura de gatilhos
  - mantido por `signals/core/redis.py` e `monitoring/core/redis.py`

Diferença legítima:
- A coexistência de `signal:{id}` e `signals:*` é **funcionalmente legítima**:
  - `signal:{id}` representa estado/snapshot por entidade
  - `signals:*` representa índices auxiliares (ativos/dedupe)

Inconsistência histórica (ponto crítico identificado):
- O principal problema **não é a nomenclatura** singular/plural por si só.
- O principal problema era a **divergência entre leitura e limpeza/reset**:
  - API listava por `signal:*` (`GET /signals`)
  - API resetava por `signals:*` (`DELETE /signals`)
  - script limpava `signal:*` + `signals:active`, sem cobrir todo o conjunto canônico

Riscos operacionais:
- limpeza parcial (dados continuam visíveis após reset parcial)
- estado órfão (índices e snapshots fora de sincronia)
- comportamento inconsistente entre reset via API e reset via script
- bugs silenciosos em operação e troubleshooting

Recomendação futura (sem breaking change e sem renomear keys):
1. Alinhar o escopo de reset entre API e script (mesmo conjunto canônico de keys).
2. Centralizar a rotina de limpeza em um único fluxo/referência operacional.
3. Manter as keys atuais (`signal:{id}`, `signals:active`, `signals:index:triggers`) e corrigir apenas o escopo de limpeza.

### 8.8 Signal Cleanup Aligned
- Evidência: `✅ Confirmado`
- Objetivo da etapa:
  - alinhar reset operacional sem renomear keys nem alterar contratos Redis

Conjunto canônico de keys de sinais:
1. `signal:*`
2. `signals:active`
3. `signals:index:triggers`

Escopo exato do `DELETE /signals` (API):
- implementado em `apps/api/routes/signals.py`
- limpa exatamente o conjunto canônico acima
- não limpa streams nem consumer groups

Escopo exato de `apps/monitoring/clear_signals.sh`:
- modo `signals`: limpa exatamente o conjunto canônico de sinais
- modo `hard` (padrão): limpa conjunto canônico + `streams:signals:new` + `streams:signals:updates` + `XGROUP DESTROY` dos grupos relacionados

Diferença entre cleanup de sinais e hard reset:
- `cleanup de sinais`:
  - remove snapshots e índices de sinais
  - preserva infraestrutura de stream/group
- `hard reset`:
  - inclui limpeza de stream e destruição de consumer groups
  - uso mais agressivo para recuperação operacional completa

## 10) Incertezas e Validação Manual Necessária
1. Se `apps/bot_automatico/bot.js` (consumidor de streams) ainda é usado operacionalmente em algum ambiente.
2. Se a ausência de publish em Pragmatic é intencional por estratégia de coleta ou dívida técnica.
3. Se há jobs externos de limpeza Redis que compensam a divergência `signal:*` vs `signals:*`.

## 11) Desenvolvimento Local com SSH Tunnel (API)

Objetivo: permitir que a API local conecte no Redis remoto sem acesso direto de rede ao host do Redis.

### 11.1 Exemplo de túnel

```bash
ssh -N -L 6380:127.0.0.1:6379 usuario@servidor
```

Com isso:
- `127.0.0.1:6380` (máquina local) aponta para `127.0.0.1:6379` no servidor remoto.

### 11.2 Prioridade de configuração da conexão Redis na API

1. `REDIS_CONNECT` (preferencial)
2. fallback para `REDIS_HOST` + `REDIS_PORT` + `REDIS_PASSWORD` (+ `REDIS_DB`, opcional)

### 11.3 Formatos suportados

Formato 1 (preferencial):

```bash
REDIS_CONNECT=redis://:PASSWORD@127.0.0.1:6380/0
```

Formato 2:

```bash
REDIS_HOST=127.0.0.1
REDIS_PORT=6380
REDIS_PASSWORD=PASSWORD
REDIS_DB=0
```

### 11.4 Timeouts e resiliência da conexão (API)

Parâmetros padrão usados pelo cliente Redis centralizado da API:
- `socket_timeout=5.0`
- `socket_connect_timeout=5.0`
- `retry_on_timeout=true`
- `health_check_interval=30`

Também podem ser sobrescritos por ambiente:
- `REDIS_SOCKET_TIMEOUT`
- `REDIS_CONNECT_TIMEOUT`
- `REDIS_RETRY_ON_TIMEOUT`
- `REDIS_HEALTH_CHECK_INTERVAL`

### 11.5 Contratos Redis

Esta mudança altera apenas a forma de conexão da API e **não altera contratos** de canais/streams/chaves:
- `streams:signals:new`
- `streams:signals:updates`
- `pubsub:new_result` (e correlatos)
- `signal:{id}`
- `signals:*`

### 11.6 Desenvolvimento Híbrido (Signals/Monitoring)

Objetivo: em desenvolvimento local, manter **sinais no Redis local** e consumir **resultados via túnel SSH**.

Exemplo de túnel:

```bash
ssh -N -L 6380:127.0.0.1:6379 usuario@servidor
```

Exemplo de `.env` para esse cenário:

```bash
# Redis local para gravação/atualização/visualização de sinais
REDIS_SIGNALS_CONNECT=redis://127.0.0.1:6379/0

# Redis remoto (via túnel) para receber new_result/new_result_simulate
REDIS_RESULTS_CONNECT=redis://127.0.0.1:6380/0

# Canal de resultados (opcional)
RESULT_CHANNEL=new_result
```

Fallbacks suportados:
1. Se `REDIS_SIGNALS_CONNECT` não existir, usa `REDIS_CONNECT`.
2. Se `REDIS_RESULTS_CONNECT` não existir, usa o mesmo Redis de sinais.

Assim, produção segue compatível sem alteração de contratos, e o ambiente local pode separar leitura de resultados de persistência de sinais.

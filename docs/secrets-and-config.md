# Secrets and Config Hardening (Mapeamento)

## Escopo e critério
- Escopo deste documento: mapeamento, classificação e status incremental de hardening.
- Runtime principal considerado: apps gerenciados por PM2 em `infra/pm2/ecosystem.config.js` (`api`, `collector`, `signals`, `monitoring`, `auth_api`, `bot_automatico`).
- Classificação usada por item:
  - `ENV imediato`: deve sair do código agora na próxima etapa de implementação.
  - `Fallback + warning`: pode manter fallback temporário para compatibilidade, com aviso em log.
  - `Documentar por enquanto`: manter como está nesta fase por ser legado/incerto/uso manual.
- Evidência:
  - `Confirmado`: visto diretamente no código.
  - `Inferido`: comportamento provável pelo fluxo.
  - `Incerto`: exige validação manual de uso real em operação.

## 1) Segredos em runtime principal

| Item | Arquivo(s) | Evidência | Risco | Ação | Env sugerida | Impacto esperado |
|---|---|---|---|---|---|---|
| Credenciais de login hardcoded no bot principal (`AUTH_EMAIL`, `AUTH_PASSWORD`) | `apps/bot_automatico/main.js:20-23`, `apps/bot_automatico/main.js:31-36` | Confirmado | Crítico (exposição direta de credencial em app de produção) | `ENV imediato (migração iniciada)` | `AUTH_EMAIL`, `AUTH_PASSWORD` | Baixo/médio (env já é preferencial; fallback temporário com warning) |
| Fallback de `MONGO_URL` com credenciais embutidas (Evolution collector) | `apps/collector/collector_ws_evolution.py:13-18`, `apps/collector/collector_ws_evolution.py:29-30` | Confirmado | Crítico (string de conexão sensível no código) | `ENV imediato (migração iniciada)` | `MONGO_URL` | Baixo (env preferencial; fallback temporário com warning) |
| Credenciais hardcoded de provedor externo (Evolution login payload) | `apps/collector/collector_ws_evolution.py:40-48`, `apps/collector/collector_ws_evolution.py:53-58` | Confirmado | Crítico (senha de terceiro embutida) | `ENV imediato (migração iniciada)` | `EVOLUTION_USERNAME`, `EVOLUTION_PASSWORD` | Médio (env preferencial; fallback temporário com warning) |
| Fallback de `MONGO_URL` com credenciais embutidas (Pragmatic collector) | `apps/collector/collector_ws_pragmatic.py:13-23` | Confirmado | Alto | `ENV imediato (migração iniciada)` | `MONGO_URL` | Baixo (env preferencial; fallback temporário com warning) |
| Fallback de `MONGO_URL` com credenciais embutidas (Ezugi collector) | `apps/collector/collector_ws_ezugi.py:15-25` | Confirmado | Alto | `ENV imediato (migração iniciada)` | `MONGO_URL` | Baixo (env preferencial; fallback temporário com warning) |

## 2) Configurações operacionais em runtime principal

| Item | Arquivo(s) | Evidência | Tipo | Ação | Env sugerida | Observação |
|---|---|---|---|---|---|---|
| Base URL interna do auth no bot (`AUTH_BASE_URL`) com fallback | `apps/bot_automatico/main.js:19` | Confirmado | URL interna | `Fallback + warning` | `AUTH_BASE_URL` | Manter fallback temporário evita quebra local; logar quando fallback for usado |
| Porta HTTP do bot (`API_PORT`) com fallback 3000 | `apps/bot_automatico/main.js:24` | Confirmado | Porta | `Fallback + warning` | `API_PORT` | Útil em dev; em produção preferir env explícita |
| URLs externas da casa de apostas hardcoded no auth_api (login/me/start-game/legitimuz) | `apps/auth_api/routes/index.ts:49`, `:102`, `:167`, `:201`, `:236` | Confirmado | Endpoint externo | `Fallback + warning` | `BOOKMAKER_BASE_URL` | Centralizar host base em env e montar rotas dinamicamente na implementação |
| Headers `origin`/`referer` hardcoded no auth_api | `apps/auth_api/routes/index.ts:56`, `:58`, `:107`, `:108`, `:171`, `:172`, `:205`, `:206`, `:243`, `:244` | Confirmado | Config operacional de integração | `Fallback + warning` | `BOOKMAKER_ORIGIN`, `BOOKMAKER_REFERER_BASE` | Evita drift quando domínio/parceiro mudar |
| Porta do auth_api com default 3090 | `apps/auth_api/main.ts:72` | Confirmado | Porta | `Fallback + warning` | `PORT` | Default local aceitável; produção deve definir explicitamente |
| URL de bet API no monitoring com fallback localhost | `apps/monitoring/src/processor_monitoring.py:97` | Confirmado | URL interna | `Fallback + warning` | `BET_API_URL` | Hoje pode mascarar configuração ausente |
| Redis da API WS com fallback localhost | `apps/api/routes/websocket_signals.py:20` | Confirmado | Infra interna | `Fallback + warning` | `REDIS_CONNECT` | Em produção, fallback para localhost tende a erro silencioso |
| Porta do collector dummy HTTP com default 8080 | `apps/collector/main.py:20` | Confirmado | Porta | `Fallback + warning` | `PORT` | Em PM2 pode conflitar se mal definido |
| Mongo sem fallback em collector_ws_miguel (exige env obrigatório) | `apps/collector/collector_ws_miguel.py:12` | Confirmado | Config obrigatória | `Documentar por enquanto` | `MONGO_URL` | Já está no formato correto (sem segredo hardcoded), manter |
| Config padrão em API (`mongo_url`, `redis_connect`, `port`) via settings | `apps/api/core/config.py:5-7`, `apps/api/start.py:16` | Confirmado | Config centralizada | `Documentar por enquanto` | `MONGO_URL`, `REDIS_CONNECT`, `PORT` | Padrão atual é bom e reaproveitável |

## 3) Segredos/configs em scripts legados ou uso manual

| Item | Arquivo(s) | Evidência | Risco | Ação | Env sugerida | Prioridade |
|---|---|---|---|---|---|---|
| Script legado `bot.js` com email/senha e Redis URL com senha hardcoded | `apps/bot_automatico/bot.js:10`, `:11`, `:29` | Confirmado | Crítico | `Documentar por enquanto` | `AUTH_EMAIL`, `AUTH_PASSWORD`, `REDIS_CONNECT` | Média (fora do runtime PM2, mas risco real se reutilizado) |
| Scripts legados de bot com fallback inseguro para credenciais | `apps/bot_automatico/bot_auto.js:20-21` (e variantes `bot_auto_1.js`, `bot_auto_novo.js`, `bot_api.js`, `bot_reinsvest.js`) | Confirmado | Alto | `Documentar por enquanto` | `AUTH_EMAIL`, `AUTH_PASSWORD` | Média |
| Script operacional com senha Redis remota hardcoded | `apps/monitoring/clear_signals.sh:16-31`, `apps/monitoring/clear_signals.sh:43-47` | Confirmado | Crítico | `ENV imediato (migração iniciada)` | `REDIS_CONNECT` (preferencial), `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD` | Alta (já prioriza env; fallback hardcoded final mantido com warning) |
| Script legado Evolution com `EVOSESSIONID` embutido na URL | `apps/collector/collector_ws_evolution_back.py:10` | Confirmado | Alto | `Documentar por enquanto` | `EVOLUTION_WS_URL` | Média/baixa (arquivo de backup/legado) |
| Padrões em `signals/patterns` com Redis URL sensível hardcoded | `apps/signals/patterns/automatico.py:26`, `apps/signals/patterns/chat_auto.py:11` | Confirmado | Alto | `Documentar por enquanto` | `REDIS_CONNECT` | Média |
| Padrões em `signals/patterns` com token/chat Telegram hardcoded | `apps/signals/patterns/super1.py:75-76`, `apps/signals/patterns/similaridade_original.py:16-17`, `apps/signals/patterns/padraotb.py:20-21` | Confirmado | Alto | `Documentar por enquanto` | `TELEGRAM_TOKEN`, `CHAT_ID` | Média |
| Template de teste com token explícito em URL de iframe | `apps/api/templates/test_iframe.html:15` | Confirmado | Alto | `Documentar por enquanto` | `TEST_IFRAME_URL` (se mantiver) | Baixa (teste/manual) |
| Front de teste com URL fixa de bot local | `apps/api/templates/api.html:3367-3368` | Confirmado | Operacional | `Documentar por enquanto` | `BOT_API_URL`, `BOT_HEALTH_URL` | Baixa |
| Arquivos `.env` presentes no workspace (chaves sensíveis detectadas) | `.env`, `apps/bot_automatico/.env` | Confirmado (local) / Incerto (versionamento) | Alto se versionado | `Documentar por enquanto` | n/a | Alta para validação manual de git tracking |

## O que deve virar env imediatamente
1. Credenciais hardcoded no runtime PM2 (`bot_automatico/main.js` e collectors principais).
2. `MONGO_URL` com fallback sensível em collectors.
3. Credenciais de login do provedor no `collector_ws_evolution.py`.
4. Senha/host Redis hardcoded no script operacional `apps/monitoring/clear_signals.sh`.

## Migração iniciada nesta etapa (runtime principal)
1. `apps/bot_automatico/main.js` agora prioriza `AUTH_EMAIL` e `AUTH_PASSWORD`, mantendo fallback hardcoded temporário com warning.
2. `apps/collector/collector_ws_evolution.py` agora prioriza `MONGO_URL`, `EVOLUTION_USERNAME` e `EVOLUTION_PASSWORD`, mantendo fallback hardcoded temporário com warning.
3. `apps/collector/collector_ws_pragmatic.py` e `apps/collector/collector_ws_ezugi.py` agora priorizam `MONGO_URL`, mantendo fallback hardcoded temporário com warning.
4. `apps/monitoring/clear_signals.sh` agora prioriza `REDIS_CONNECT`; se ausente usa `REDIS_HOST`/`REDIS_PORT`/`REDIS_PASSWORD`; só depois cai no fallback hardcoded final com warning.
5. Warnings adicionados nesta etapa não imprimem valores de segredo, apenas o nome da env ausente e o modo de fallback.

## O que pode ter fallback temporário com warning
1. URLs e portas operacionais internas/externas do runtime principal (`AUTH_BASE_URL`, `BET_API_URL`, `PORT`, `BOOKMAKER_BASE_URL`).
2. `REDIS_CONNECT` em pontos que hoje caem para localhost, desde que haja warning explícito quando fallback for acionado.
3. Headers operacionais (`origin`/`referer`) enquanto o host externo não for parametrizado por completo.

## O que deve apenas ser documentado por enquanto (legado/incerto)
1. Scripts legados fora do entrypoint PM2 (ex.: `bot.js`, `collector_ws_evolution_back.py`, arquivos em `signals/patterns`).
2. Templates/páginas de teste que não participam do runtime principal.
3. Arquivos `.env` locais até validar se estão ou não versionados no repositório remoto.

## Estratégia de rollout recomendada (sem breaking change)
1. Endurecer primeiro o runtime principal: remover segredos hardcoded e exigir env obrigatória para credenciais.
2. Em seguida, parametrizar configurações operacionais com fallback temporário + warning.
3. Depois, revisar scripts legados/manual e decidir por migração, isolamento ou descontinuação.

## Recomendação operacional (etapa posterior)
- Gerar `/.env.example` por app **somente na próxima etapa** (não criar arquivos nesta fase documental), após concluir a migração dos itens `ENV imediato`.

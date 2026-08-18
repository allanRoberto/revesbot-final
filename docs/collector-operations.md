# Operacao do collector Pragmatic

## Escopo da primeira etapa

O collector do servidor novo grava exclusivamente em:

- MongoDB local: `roleta_db_collector_test.history`
- Redis local: canal `new_result_test`

O collector do servidor atual continua em producao. Nenhum dado capturado pelo
novo servidor e consumido pela API de producao nesta etapa.

## Layout do servidor

```text
/var/www/revesbot/
  repository/
  releases/<git-sha>/
  current -> releases/<git-sha>
  shared/state/
  data/mongo-test/
  data/redis-test/

/etc/revesbot/
  collector.env
  collector-data-test.env
```

## Health checks

```bash
curl http://127.0.0.1:9101/health/live
curl http://127.0.0.1:9101/health/ready
curl http://127.0.0.1:9101/metrics
```

O endpoint `ready` exige MongoDB, Redis, WebSocket e resultados recentes. O
watchdog interno encerra processos obsoletos; PM2 reinicia o worker e o timer
systemd funciona como segunda camada.

As metricas `revesbot_collector_recovered_results_total` e
`revesbot_collector_recovery_failures_total` mostram, respectivamente, quantos
resultados foram recompostos e quantas vezes a interrupcao ultrapassou a janela
de 20 resultados disponibilizada pelo provedor.

Os logs do collector giram diariamente ou ao atingir 20 MB. Sao mantidos sete
arquivos compactados, evitando crescimento indefinido no disco.

## Migracao da collection history

A primeira etapa de producao migra somente `roleta_db.history`. O MongoDB de
producao roda em `127.0.0.1:27018`, separado do banco de teste em `27017`.

1. Execute `bootstrap-data-prod.sh` no servidor novo.
2. Ative o tunel `revesbot-redis-tunnel.service`; ele expoe o Redis legado
   somente em `127.0.0.1:6380` no servidor novo.
3. Gere a carga inicial com `migrate-history.sh source-full` no servidor atual.
4. Transfira arquivo, checksum e limite de ObjectId para o servidor novo.
5. Restaure com `migrate-history.sh target-full` e valide contagem e indices.
6. Pare o collector antigo, gere `source-delta` a partir do limite inicial e
   restaure com `target-delta`.
7. Execute `cutover.sh` somente depois das contagens coincidirem.

O cutover preserva `/etc/revesbot/collector.env.pre-history-cutover` e volta ao
collector de teste automaticamente se MongoDB, Redis ou healthcheck falharem.
As demais collections continuam no servidor antigo nesta etapa.

## Conferencia da captura

Com as variaveis do collector carregadas, o diagnostico abaixo informa a
quantidade de documentos, mesas, ultimo resultado e grupos duplicados, sem
exibir credenciais:

```bash
/var/www/revesbot/current/.venv/bin/python \
  /var/www/revesbot/current/apps/collector/scripts/verify_capture.py
```

## Deploy e rollback

O workflow `deploy-collector.yml` testa e implanta o SHA exato enviado ao
branch `main`. O script mantém tres releases e reverte o symlink `current` se o
health check nao ficar pronto.

A chave do GitHub Actions usa `restrict` e um comando SSH forcado. Mesmo em
caso de exposicao, ela nao abre shell: aceita somente um SHA Git de 40
caracteres e executa exclusivamente o deploy do collector.

## Validacao antes da migracao

1. Manter os collectors antigo e novo ativos simultaneamente.
2. Comparar por mesa `external_game_id`, numero e horario.
3. Testar desconexao e confirmar recuperacao via `last20Results`.
4. Testar indisponibilidade temporaria do MongoDB/Redis.
5. Confirmar reinicio pelo watchdog e PM2.
6. Observar pelo menos 24 horas sem lacunas antes de planejar o corte.

## Remocao dos dados de teste

Antes da restauracao do banco de producao, parar o collector de teste e apagar
somente o banco `roleta_db_collector_test`. O diretorio de dados do MongoDB nao
deve ser apagado, pois tambem recebera a restauracao futura.

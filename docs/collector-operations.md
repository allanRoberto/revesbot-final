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

Os logs do collector giram diariamente ou ao atingir 20 MB. Sao mantidos sete
arquivos compactados, evitando crescimento indefinido no disco.

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

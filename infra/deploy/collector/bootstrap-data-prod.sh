#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Execute como root." >&2
  exit 1
fi

base_dir="${REVESBOT_BASE_DIR:-/var/www/revesbot}"
runtime_user="${REVESBOT_RUNTIME_USER:-revesbot}"
compose_file="${COLLECTOR_PROD_COMPOSE_FILE:-$base_dir/current/infra/docker/collector-prod.compose.yml}"
data_env=/etc/revesbot/collector-data-prod.env
collector_env=/etc/revesbot/collector-prod.env

command -v docker >/dev/null
docker compose version >/dev/null
test -f "$compose_file"

install -d -m 0750 -o root -g "$runtime_user" /etc/revesbot
install -d -o 999 -g 999 "$base_dir/data/mongo-prod"

if [[ ! -s "$data_env" ]]; then
  mongo_root_password="$(openssl rand -hex 24)"
  mongo_collector_password="$(openssl rand -hex 24)"
  data_env_next="$(mktemp /etc/revesbot/collector-data-prod.env.XXXXXX)"
  trap 'rm -f "$data_env_next"' EXIT
  umask 0077
  {
    printf 'MONGO_INITDB_ROOT_USERNAME=%s\n' 'revesbot_root_prod'
    printf 'MONGO_INITDB_ROOT_PASSWORD=%s\n' "$mongo_root_password"
    printf 'MONGO_COLLECTOR_USERNAME=%s\n' 'revesbot_collector_prod'
    printf 'MONGO_COLLECTOR_PASSWORD=%s\n' "$mongo_collector_password"
  } > "$data_env_next"
  chown root:"$runtime_user" "$data_env_next"
  chmod 0640 "$data_env_next"
  mv "$data_env_next" "$data_env"
  trap - EXIT
fi

set -a
# shellcheck disable=SC1090
source "$data_env"
set +a

docker compose -f "$compose_file" up -d

install -m 0644 "$base_dir/current/infra/systemd/revesbot-redis-tunnel.service" \
  /etc/systemd/system/revesbot-redis-tunnel.service
systemctl daemon-reload

mongo_ready=false
for _attempt in $(seq 1 45); do
  if docker exec revesbot-mongo-prod mongosh --quiet \
      --username "$MONGO_INITDB_ROOT_USERNAME" \
      --password "$MONGO_INITDB_ROOT_PASSWORD" \
      --authenticationDatabase admin \
      --eval 'quit(db.runCommand({ping:1}).ok ? 0 : 2)' >/dev/null 2>&1; then
    mongo_ready=true
    break
  fi
  sleep 2
done
if [[ "$mongo_ready" != true ]]; then
  echo "MongoDB de producao nao autenticou dentro do prazo." >&2
  exit 1
fi

docker exec revesbot-mongo-prod mongosh --quiet \
  --username "$MONGO_INITDB_ROOT_USERNAME" \
  --password "$MONGO_INITDB_ROOT_PASSWORD" \
  --authenticationDatabase admin \
  --eval "const target=db.getSiblingDB('roleta_db'); const user='$MONGO_COLLECTOR_USERNAME'; const pwd='$MONGO_COLLECTOR_PASSWORD'; if (target.getUser(user)) { target.updateUser(user,{pwd:pwd,roles:[{role:'readWrite',db:'roleta_db'}]}); } else { target.createUser({user:user,pwd:pwd,roles:[{role:'readWrite',db:'roleta_db'}]}); }" \
  >/dev/null

collector_env_next="$(mktemp /etc/revesbot/collector-prod.env.XXXXXX)"
trap 'rm -f "$collector_env_next"' EXIT
umask 0077
{
  printf 'DEPLOY_STAGE=%s\n' 'collector-production'
  printf 'COLLECTOR_PROCESS_NAME=%s\n' 'collector-pragmatic'
  printf 'MONGO_URL=mongodb://%s:%s@127.0.0.1:27018/roleta_db?authSource=roleta_db\n' \
    "$MONGO_COLLECTOR_USERNAME" "$MONGO_COLLECTOR_PASSWORD"
  printf 'MONGO_DATABASE=%s\n' 'roleta_db'
  printf 'MONGO_COLLECTION=%s\n' 'history'
  printf 'REDIS_CONNECT=%s\n' 'redis://127.0.0.1:6380/0'
  printf 'RESULT_CHANNEL=%s\n' 'new_result'
  printf 'PRAGMATIC_CASINO_ID=%s\n' 'ppcdd00000006702'
  printf 'COLLECTOR_HEALTH_HOST=%s\n' '127.0.0.1'
  printf 'COLLECTOR_HEALTH_PORT=%s\n' '9101'
  printf 'COLLECTOR_WS_STALE_SECONDS=%s\n' '90'
  printf 'COLLECTOR_RESULT_STALE_SECONDS=%s\n' '180'
  printf 'COLLECTOR_STARTUP_GRACE_SECONDS=%s\n' '120'
  printf 'COLLECTOR_WATCHDOG_INTERVAL_SECONDS=%s\n' '15'
  printf 'COLLECTOR_WATCHDOG_FAILURES=%s\n' '3'
  printf 'COLLECTOR_WATCHDOG_EXIT_ENABLED=%s\n' 'true'
  printf 'COLLECTOR_EXTERNAL_WATCHDOG_FAILURES=%s\n' '2'
  printf 'COLLECTOR_RETENTION_LIMIT=%s\n' '200000'
  printf 'COLLECTOR_RETENTION_INTERVAL_SECONDS=%s\n' '300'
  printf 'LOG_LEVEL=%s\n' 'INFO'
} > "$collector_env_next"
chown root:"$runtime_user" "$collector_env_next"
chmod 0640 "$collector_env_next"
mv "$collector_env_next" "$collector_env"
trap - EXIT

echo "MongoDB de producao pronto em 127.0.0.1:27018; credenciais nao exibidas."

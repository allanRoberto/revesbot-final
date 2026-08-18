#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Execute como root." >&2
  exit 1
fi

base_dir="${REVESBOT_BASE_DIR:-/var/www/revesbot}"
repository="$base_dir/repository"
data_env=/etc/revesbot/collector-data-test.env
collector_env=/etc/revesbot/collector.env
runtime_user="${REVESBOT_RUNTIME_USER:-revesbot}"

test -s "$data_env"
test -f "$repository/infra/docker/collector-test.compose.yml"

set -a
# shellcheck disable=SC1090
source "$data_env"
set +a

new_mongo_collector_password="$(openssl rand -hex 24)"
new_redis_password="$(openssl rand -hex 24)"

docker exec revesbot-mongo-test mongosh --quiet \
  --username "$MONGO_INITDB_ROOT_USERNAME" \
  --password "$MONGO_INITDB_ROOT_PASSWORD" \
  --authenticationDatabase admin \
  --eval "db.getSiblingDB('roleta_db_collector_test').updateUser('$MONGO_COLLECTOR_USERNAME',{pwd:'$new_mongo_collector_password',roles:[{role:'readWrite',db:'roleta_db_collector_test'}]})" \
  >/dev/null

data_env_next="$(mktemp /etc/revesbot/collector-data-test.env.XXXXXX)"
collector_env_next="$(mktemp /etc/revesbot/collector.env.XXXXXX)"
trap 'rm -f "$data_env_next" "$collector_env_next"' EXIT

umask 0077
{
  printf 'MONGO_INITDB_ROOT_USERNAME=%s\n' "$MONGO_INITDB_ROOT_USERNAME"
  printf 'MONGO_INITDB_ROOT_PASSWORD=%s\n' "$MONGO_INITDB_ROOT_PASSWORD"
  printf 'MONGO_COLLECTOR_USERNAME=%s\n' "$MONGO_COLLECTOR_USERNAME"
  printf 'MONGO_COLLECTOR_PASSWORD=%s\n' "$new_mongo_collector_password"
  printf 'REDIS_PASSWORD=%s\n' "$new_redis_password"
} > "$data_env_next"

{
  printf 'DEPLOY_STAGE=%s\n' 'collector-test'
  printf 'COLLECTOR_PROCESS_NAME=%s\n' 'collector-pragmatic-test'
  printf 'MONGO_URL=mongodb://%s:%s@127.0.0.1:27017/roleta_db_collector_test?authSource=roleta_db_collector_test\n' \
    "$MONGO_COLLECTOR_USERNAME" "$new_mongo_collector_password"
  printf 'MONGO_DATABASE=%s\n' 'roleta_db_collector_test'
  printf 'MONGO_COLLECTION=%s\n' 'history'
  printf 'REDIS_CONNECT=redis://:%s@127.0.0.1:6379/0\n' "$new_redis_password"
  printf 'RESULT_CHANNEL=%s\n' 'new_result_test'
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

chown root:"$runtime_user" "$data_env_next" "$collector_env_next"
chmod 0640 "$data_env_next" "$collector_env_next"
mv -f "$data_env_next" "$data_env"
mv -f "$collector_env_next" "$collector_env"
trap - EXIT

docker compose -f "$repository/infra/docker/collector-test.compose.yml" up -d --force-recreate redis-test

echo "Credenciais de teste renovadas."

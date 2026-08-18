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

command -v docker >/dev/null
docker compose version >/dev/null
test -f "$repository/infra/docker/collector-test.compose.yml"

install -d -m 0750 -o root -g "$runtime_user" /etc/revesbot
install -d -o 999 -g 999 "$base_dir/data/mongo-test"
install -d -o 999 -g 999 "$base_dir/data/redis-test"

if [[ ! -s "$data_env" ]]; then
  mongo_root_password="$(openssl rand -hex 24)"
  mongo_collector_password="$(openssl rand -hex 24)"
  redis_password="$(openssl rand -hex 24)"
  umask 0077
  {
    printf 'MONGO_INITDB_ROOT_USERNAME=%s\n' 'revesbot_root'
    printf 'MONGO_INITDB_ROOT_PASSWORD=%s\n' "$mongo_root_password"
    printf 'MONGO_COLLECTOR_USERNAME=%s\n' 'revesbot_collector_test'
    printf 'MONGO_COLLECTOR_PASSWORD=%s\n' "$mongo_collector_password"
    printf 'REDIS_PASSWORD=%s\n' "$redis_password"
  } > "$data_env"
  chown root:"$runtime_user" "$data_env"
  chmod 0640 "$data_env"
fi

set -a
# shellcheck disable=SC1090
source "$data_env"
set +a

docker compose -f "$repository/infra/docker/collector-test.compose.yml" up -d

for _attempt in $(seq 1 30); do
  if docker exec revesbot-mongo-test mongosh --quiet \
      --username "$MONGO_INITDB_ROOT_USERNAME" \
      --password "$MONGO_INITDB_ROOT_PASSWORD" \
      --authenticationDatabase admin \
      --eval 'quit(db.runCommand({ping:1}).ok ? 0 : 2)' >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

docker exec revesbot-mongo-test mongosh --quiet \
  --username "$MONGO_INITDB_ROOT_USERNAME" \
  --password "$MONGO_INITDB_ROOT_PASSWORD" \
  --authenticationDatabase admin \
  --eval "const target=db.getSiblingDB('roleta_db_collector_test'); const user='$MONGO_COLLECTOR_USERNAME'; const pwd='$MONGO_COLLECTOR_PASSWORD'; if (target.getUser(user)) { target.updateUser(user,{pwd:pwd,roles:[{role:'readWrite',db:'roleta_db_collector_test'}]}); } else { target.createUser({user:user,pwd:pwd,roles:[{role:'readWrite',db:'roleta_db_collector_test'}]}); }" >/dev/null

umask 0077
{
  printf 'DEPLOY_STAGE=%s\n' 'collector-test'
  printf 'COLLECTOR_PROCESS_NAME=%s\n' 'collector-pragmatic-test'
  printf 'MONGO_URL=mongodb://%s:%s@127.0.0.1:27017/roleta_db_collector_test?authSource=roleta_db_collector_test\n' \
    "$MONGO_COLLECTOR_USERNAME" "$MONGO_COLLECTOR_PASSWORD"
  printf 'MONGO_DATABASE=%s\n' 'roleta_db_collector_test'
  printf 'MONGO_COLLECTION=%s\n' 'history'
  printf 'REDIS_CONNECT=redis://:%s@127.0.0.1:6379/0\n' "$REDIS_PASSWORD"
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
} > "$collector_env"
chown root:"$runtime_user" "$collector_env"
chmod 0640 "$collector_env"

echo "MongoDB e Redis de teste estao prontos em localhost. Segredos nao foram exibidos."

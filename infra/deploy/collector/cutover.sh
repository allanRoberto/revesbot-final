#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Execute como root." >&2
  exit 1
fi
if [[ "${COLLECTOR_CUTOVER_CONFIRMED:-}" != "history-only" ]]; then
  echo "Defina COLLECTOR_CUTOVER_CONFIRMED=history-only." >&2
  exit 2
fi

base_dir="${REVESBOT_BASE_DIR:-/var/www/revesbot}"
runtime_user="${REVESBOT_RUNTIME_USER:-revesbot}"
active_env=/etc/revesbot/collector.env
prod_env=/etc/revesbot/collector-prod.env
rollback_env=/etc/revesbot/collector.env.pre-history-cutover
pm2_home="/home/$runtime_user/.pm2"
pm2_config="$base_dir/current/infra/pm2/collector.config.js"
healthcheck="$base_dir/current/infra/deploy/collector/healthcheck.sh"

test -s "$active_env"
test -s "$prod_env"
test -f "$pm2_config"
test -x "$healthcheck"
systemctl is-active --quiet revesbot-redis-tunnel.service
docker inspect revesbot-mongo-prod >/dev/null

if [[ ! -e "$rollback_env" ]]; then
  install -m 0640 -o root -g "$runtime_user" "$active_env" "$rollback_env"
fi

rollback() {
  echo "Cutover falhou; restaurando collector de teste." >&2
  install -m 0640 -o root -g "$runtime_user" "$rollback_env" "$active_env"
  set -a
  # shellcheck disable=SC1090
  source "$active_env"
  set +a
  sudo -u "$runtime_user" env PM2_HOME="$pm2_home" pm2 delete collector-pragmatic >/dev/null 2>&1 || true
  sudo -u "$runtime_user" --preserve-env \
    env PM2_HOME="$pm2_home" REVESBOT_CURRENT="$base_dir/current" \
    pm2 startOrReload "$pm2_config" --update-env
  systemctl start revesbot-collector-watchdog.timer
}
trap rollback ERR

systemctl stop revesbot-collector-watchdog.timer
sudo -u "$runtime_user" env PM2_HOME="$pm2_home" pm2 stop collector-pragmatic-test >/dev/null 2>&1 || true
install -m 0640 -o root -g "$runtime_user" "$prod_env" "$active_env"

set -a
# shellcheck disable=SC1090
source "$active_env"
set +a

cd "$base_dir/current/apps/collector"
sudo -u "$runtime_user" --preserve-env=MONGO_URL,REDIS_CONNECT,MONGO_DATABASE,MONGO_COLLECTION \
  "$base_dir/current/.venv/bin/python" -c \
  'from collector.config import CollectorSettings; CollectorSettings.from_env(); print("config-ok")'

sudo -u "$runtime_user" --preserve-env \
  env PM2_HOME="$pm2_home" REVESBOT_CURRENT="$base_dir/current" \
  pm2 startOrReload "$pm2_config" --update-env
"$healthcheck"

sudo -u "$runtime_user" env PM2_HOME="$pm2_home" pm2 delete collector-pragmatic-test >/dev/null 2>&1 || true
sudo -u "$runtime_user" env PM2_HOME="$pm2_home" pm2 save
systemctl start revesbot-collector-watchdog.timer
trap - ERR

echo "Cutover concluido: collector-pragmatic usa roleta_db.history."

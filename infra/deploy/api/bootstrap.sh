#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Execute como root." >&2
  exit 1
fi

base_dir="${REVESBOT_BASE_DIR:-/var/www/revesbot}"
runtime_user="${REVESBOT_RUNTIME_USER:-revesbot}"
repository="$base_dir/repository"
source_root="${REVESBOT_SOURCE_ROOT:-$repository}"
api_env=/etc/revesbot/api.env
mongo_data_env=/etc/revesbot/collector-data-prod.env

command -v git >/dev/null
command -v pm2 >/dev/null
command -v nginx >/dev/null
test -d "$repository/.git"
test -f "$source_root/infra/pm2/api-minimal.config.js"
test -s "$mongo_data_env"

install -d -o "$runtime_user" -g "$runtime_user" "$base_dir/api-releases"
install -d -o "$runtime_user" -g "$runtime_user" "$base_dir/shared/state"
install -d -m 0750 -o root -g "$runtime_user" /etc/revesbot

if [[ ! -s "$api_env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$mongo_data_env"
  set +a
  api_user=revesbot_api_prod
  api_password="$(openssl rand -hex 24)"
  docker exec revesbot-mongo-prod mongosh --quiet \
    --username "$MONGO_INITDB_ROOT_USERNAME" \
    --password "$MONGO_INITDB_ROOT_PASSWORD" \
    --authenticationDatabase admin \
    --eval "const target=db.getSiblingDB('roleta_db'); if (target.getUser('$api_user')) { target.updateUser('$api_user',{pwd:'$api_password',roles:[{role:'read',db:'roleta_db'}]}); } else { target.createUser({user:'$api_user',pwd:'$api_password',roles:[{role:'read',db:'roleta_db'}]}); }" \
    >/dev/null
  api_env_next="$(mktemp /etc/revesbot/api.env.XXXXXX)"
  trap 'rm -f "$api_env_next"' EXIT
  umask 0077
  {
    printf 'API_PORT=%s\n' '8082'
    printf 'API_WORKERS=%s\n' '2'
    printf 'MONGO_URL=mongodb://%s:%s@127.0.0.1:27018/roleta_db?authSource=roleta_db\n' "$api_user" "$api_password"
    printf 'MONGO_DATABASE=%s\n' 'roleta_db'
    printf 'REDIS_CONNECT=%s\n' 'redis://127.0.0.1:6380/0'
    printf 'PIXGO_MONGO_DATABASE=%s\n' 'roleta_db'
    printf 'PIXGO_BASE_URL=%s\n' 'https://pixgo.org/api/v1'
    printf '%s\n' '# Preencher antes de ativar o webhook:'
    printf '%s\n' 'PIXGO_MONGO_URL='
    printf '%s\n' 'PIXGO_API_KEY='
    printf '%s\n' 'PIXGO_WEBHOOK_SECRET='
  } > "$api_env_next"
  chown root:"$runtime_user" "$api_env_next"
  chmod 0640 "$api_env_next"
  mv "$api_env_next" "$api_env"
  trap - EXIT
fi

install -m 0755 "$source_root/infra/deploy/api/ssh-dispatch.sh" /usr/local/sbin/revesbot-api-deploy-dispatch
install -m 0644 "$source_root/infra/systemd/revesbot-api-watchdog.service" /etc/systemd/system/
install -m 0644 "$source_root/infra/systemd/revesbot-api-watchdog.timer" /etc/systemd/system/
install -m 0644 "$source_root/infra/systemd/revesbot-pixgo-mongo-tunnel.service" /etc/systemd/system/
install -m 0644 "$source_root/infra/logrotate/revesbot-api" /etc/logrotate.d/revesbot-api
install -m 0644 "$source_root/infra/nginx/api-revesbot.conf" /etc/nginx/sites-available/api-revesbot.conf

sudoers_file=/etc/sudoers.d/revesbot-api-deploy
printf '%s ALL=(root) NOPASSWD: %s/infra/deploy/api/deploy.sh *\n' "$runtime_user" "$repository" > "$sudoers_file"
chmod 0440 "$sudoers_file"
visudo -cf "$sudoers_file" >/dev/null

systemctl daemon-reload
systemctl enable revesbot-api-watchdog.timer

echo "Bootstrap da API concluido. Complete PIXGO_* em $api_env antes do deploy."

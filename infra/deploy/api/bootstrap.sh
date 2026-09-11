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

install -d -m 0755 -o root -g root "$base_dir"
install -d -m 0755 -o root -g root "$base_dir/api-releases"
install -d -o "$runtime_user" -g "$runtime_user" "$base_dir/shared/state"
install -d -m 0750 -o root -g "$runtime_user" /etc/revesbot
install -d -m 0700 -o root -g root /var/lib/revesbot-api-deploy

set -a
# shellcheck disable=SC1090
source "$mongo_data_env"
set +a

if [[ ! -s "$api_env" ]]; then
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

# O webhook grava nas mesmas collections de cobranca usadas pelo app local.
# Migra instalacoes antigas que ainda apontem PIXGO_MONGO_URL para um tunel.
pixgo_mongo_url="$(awk -F= '$1 == "PIXGO_MONGO_URL" {sub(/^[^=]*=/, ""); print; exit}' "$api_env")"
if [[ "$pixgo_mongo_url" != *"@127.0.0.1:27018/"* ]]; then
  billing_user=revesbot_api_billing_prod
  billing_password="$(openssl rand -hex 24)"
  docker exec revesbot-mongo-prod mongosh --quiet \
    --username "$MONGO_INITDB_ROOT_USERNAME" \
    --password "$MONGO_INITDB_ROOT_PASSWORD" \
    --authenticationDatabase admin \
    --eval "const target=db.getSiblingDB('roleta_db'); if (target.getUser('$billing_user')) { target.updateUser('$billing_user',{pwd:'$billing_password',roles:[{role:'readWrite',db:'roleta_db'}]}); } else { target.createUser({user:'$billing_user',pwd:'$billing_password',roles:[{role:'readWrite',db:'roleta_db'}]}); }" \
    >/dev/null
  pixgo_mongo_url="mongodb://$billing_user:$billing_password@127.0.0.1:27018/roleta_db?authSource=roleta_db"
  api_env_next="$(mktemp /etc/revesbot/api.env.XXXXXX)"
  trap 'rm -f "$api_env_next"' EXIT
  awk -v value="$pixgo_mongo_url" '
    BEGIN { replaced = 0 }
    /^PIXGO_MONGO_URL=/ { print "PIXGO_MONGO_URL=" value; replaced = 1; next }
    { print }
    END { if (!replaced) print "PIXGO_MONGO_URL=" value }
  ' "$api_env" > "$api_env_next"
  chown root:"$runtime_user" "$api_env_next"
  chmod 0640 "$api_env_next"
  mv "$api_env_next" "$api_env"
  trap - EXIT
fi

systemctl disable --now revesbot-pixgo-mongo-tunnel.service >/dev/null 2>&1 || true

install -m 0755 "$source_root/infra/deploy/api/ssh-dispatch.sh" /usr/local/sbin/revesbot-api-deploy-dispatch
install -m 0755 "$source_root/infra/deploy/api/driver.sh" /usr/local/sbin/revesbot-api-deploy
install -m 0755 "$source_root/infra/deploy/api/watchdog.sh" /usr/local/sbin/revesbot-api-watchdog
install -m 0644 "$source_root/infra/systemd/revesbot-api-watchdog.service" /etc/systemd/system/
install -m 0644 "$source_root/infra/systemd/revesbot-api-watchdog.timer" /etc/systemd/system/
install -m 0644 "$source_root/infra/logrotate/revesbot-api" /etc/logrotate.d/revesbot-api
install -m 0644 "$source_root/infra/nginx/api-revesbot.conf" /etc/nginx/sites-available/api-revesbot.conf

sudoers_file=/etc/sudoers.d/revesbot-api-deploy
printf '%s ALL=(root) NOPASSWD: /usr/local/sbin/revesbot-api-deploy *\n' "$runtime_user" > "$sudoers_file"
chmod 0440 "$sudoers_file"
visudo -cf "$sudoers_file" >/dev/null

systemctl daemon-reload
systemctl enable revesbot-api-watchdog.timer

echo "Bootstrap da API concluido com MongoDB de cobranca local. Complete PIXGO_* em $api_env antes do deploy."

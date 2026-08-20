#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Execute como root." >&2
  exit 1
fi

legacy_env="${LEGACY_APP_ENV_FILE:-/etc/revesbot/app-legacy.env}"
target_env="${APP_ENV_FILE:-/etc/revesbot/app.env}"
mongo_env="${MONGO_DATA_ENV_FILE:-/etc/revesbot/collector-data-prod.env}"
runtime_user="${REVESBOT_RUNTIME_USER:-revesbot}"
database="${APP_MONGO_DATABASE:-roleta_db}"
mongo_container="${APP_MONGO_CONTAINER:-revesbot-mongo-prod}"
mongo_port="${APP_MONGO_PORT:-27018}"
app_user="${APP_MONGO_USERNAME:-revesbot_app_prod}"

test -s "$legacy_env"
test -s "$mongo_env"
if [[ -e "$target_env" && "${FORCE_APP_ENV:-0}" != "1" ]]; then
  echo "$target_env ja existe; use FORCE_APP_ENV=1 somente para uma substituicao consciente." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$mongo_env"
set +a
: "${MONGO_INITDB_ROOT_USERNAME:?usuario root do Mongo ausente}"
: "${MONGO_INITDB_ROOT_PASSWORD:?senha root do Mongo ausente}"

app_password="$(openssl rand -hex 24)"
docker exec "$mongo_container" mongosh --quiet \
  --username "$MONGO_INITDB_ROOT_USERNAME" \
  --password "$MONGO_INITDB_ROOT_PASSWORD" \
  --authenticationDatabase admin \
  --eval "const target=db.getSiblingDB('$database'); if (target.getUser('$app_user')) { target.updateUser('$app_user',{pwd:'$app_password',roles:[{role:'readWrite',db:'$database'}]}); } else { target.createUser({user:'$app_user',pwd:'$app_password',roles:[{role:'readWrite',db:'$database'}]}); }" \
  >/dev/null

target_next="$(mktemp /etc/revesbot/app.env.XXXXXX)"
trap 'rm -f "$target_next"' EXIT

LEGACY_APP_ENV_FILE="$legacy_env" TARGET_APP_ENV_FILE="$target_next" \
APP_MONGO_URL="mongodb://$app_user:$app_password@127.0.0.1:$mongo_port/$database?authSource=$database" \
APP_MONGO_DATABASE="$database" python3 - <<'PY'
import os
import shlex
from pathlib import Path

source = Path(os.environ['LEGACY_APP_ENV_FILE'])
target = Path(os.environ['TARGET_APP_ENV_FILE'])
values = {}
order = []
for raw in source.read_text().splitlines():
    stripped = raw.strip()
    if not stripped or stripped.startswith('#') or '=' not in raw:
        continue
    key, value = raw.split('=', 1)
    key = key.strip()
    if key not in values:
        order.append(key)
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    values[key] = value

overrides = {
    'APP_HOST': '127.0.0.1',
    'APP_PORT': '3002',
    'DEPLOY_STAGE': 'main',
    'NODE_ENV': 'production',
    'MONGO_URL': os.environ['APP_MONGO_URL'],
    'MONGO_DB': os.environ['APP_MONGO_DATABASE'],
    'EXPRESS_URL': 'http://127.0.0.1:3090',
    'BET_WS_URL': 'http://127.0.0.1:4060',
    'BET_WS_HOST': '127.0.0.1',
    'BET_WS_PORT': '4060',
    'AUTOMATION_APP_URL': 'http://127.0.0.1:3002',
    'HOUSE_AGENT_URL': 'http://127.0.0.1:4080',
    'HOUSE_AGENT_HOST': '127.0.0.1',
    'HOUSE_AGENT_PORT': '4080',
    'CHROME_BIN': '/usr/bin/chromium',
    'PUPPETEER_EXECUTABLE_PATH': '/usr/bin/chromium',
    'DEPLOY_AUX_SERVICES': '0',
}
for key, value in overrides.items():
    if key not in values:
        order.append(key)
    values[key] = value

required = [
    'JWT_SECRET', 'ENCRYPTION_KEY', 'BET_WS_TOKEN', 'AUTOMATION_INTERNAL_TOKEN',
    'HOUSE_AGENT_TOKEN', 'NEXT_PUBLIC_VIDEO_BASE',
]
missing = [key for key in required if not values.get(key)]
if missing:
    raise SystemExit('Variaveis obrigatorias ausentes: ' + ', '.join(missing))

target.write_text(''.join(f'{key}={shlex.quote(values[key])}\n' for key in order))
PY

chown root:"$runtime_user" "$target_next"
chmod 0640 "$target_next"
mv -f "$target_next" "$target_env"
trap - EXIT

echo "Ambiente do app provisionado em $target_env com usuario Mongo dedicado."

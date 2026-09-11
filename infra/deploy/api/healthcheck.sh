#!/usr/bin/env bash
set -euo pipefail

base_url="${API_HEALTH_BASE_URL:-http://127.0.0.1:8082}"
base_url="${base_url%/}"
slug="pragmatic-auto-roulette"
attempts="${HEALTHCHECK_ATTEMPTS:-12}"
interval="${HEALTHCHECK_INTERVAL_SECONDS:-5}"
heartbeat_max_age="${BEHAVIOR_LAB_HEARTBEAT_MAX_AGE_SECONDS:-90}"
minimum_started_at="${BEHAVIOR_LAB_MIN_STARTED_AT_EPOCH:-0}"
api_root="${REVESBOT_API_CURRENT:-/var/www/revesbot/api-current}"
runtime_user="${REVESBOT_RUNTIME_USER:-revesbot}"
env_file="${API_ENV_FILE:-/etc/revesbot/api.env}"
process_name="revesbot-behavior-lab"
redis_prefix="behavior_lab:v1"
health_key="$redis_prefix:$slug:health"
expected_release="$(basename "$(readlink -f "$api_root")")"

[[ "$attempts" =~ ^[1-9][0-9]*$ ]] || { echo "HEALTHCHECK_ATTEMPTS invalido." >&2; exit 2; }
[[ "$interval" =~ ^[0-9]+$ ]] || { echo "HEALTHCHECK_INTERVAL_SECONDS invalido." >&2; exit 2; }
[[ "$heartbeat_max_age" =~ ^[1-9][0-9]*$ ]] || {
  echo "BEHAVIOR_LAB_HEARTBEAT_MAX_AGE_SECONDS invalido." >&2
  exit 2
}
[[ "$minimum_started_at" =~ ^[0-9]+$ ]] || {
  echo "BEHAVIOR_LAB_MIN_STARTED_AT_EPOCH invalido." >&2
  exit 2
}

test -d "$api_root"
test -x "$api_root/.venv/bin/python"
test -s "$env_file"

SECRET_FILE="$env_file" /usr/bin/python3 -I -c '
import os
import pathlib
import stat

path = pathlib.Path(os.environ["SECRET_FILE"])
metadata = path.lstat()
parent = path.parent.stat()
if not stat.S_ISREG(metadata.st_mode):
    raise SystemExit("arquivo de ambiente nao e regular")
if metadata.st_uid != 0 or metadata.st_mode & 0o022:
    raise SystemExit("arquivo de ambiente nao esta protegido")
if parent.st_uid != 0 or parent.st_mode & 0o022:
    raise SystemExit("diretorio do ambiente nao esta protegido")
'

set -a
# shellcheck disable=SC1090
source "$env_file"
set +a

redis_url="${REDIS_CONNECT:-redis://127.0.0.1:6380/0}"
expected_fingerprint="$(
  sudo -u "$runtime_user" env \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH="$api_root/apps" \
    BEHAVIOR_LAB_CONFIG="$api_root/apps/behavior_lab/config/default_v1.json" \
    "$api_root/.venv/bin/python" -c \
    'from behavior_lab.config import load_config; print(load_config().fingerprint)'
)"

worker_is_online() {
  local worker_pid

  worker_pid="$(
    sudo -u "$runtime_user" \
      env PM2_HOME="/home/$runtime_user/.pm2" \
      pm2 pid "$process_name" 2>/dev/null \
      | awk 'NF { count += 1; pid = $1 } END { print count == 1 ? pid : 0 }'
  )"
  [[ "$worker_pid" =~ ^[1-9][0-9]*$ ]]
}

route_payload_is_valid() {
  local payload="$1"

  HEALTH_PAYLOAD="$payload" \
  EXPECTED_ROULETTE="$slug" \
  EXPECTED_FINGERPRINT="$expected_fingerprint" \
  EXPECTED_RELEASE="$expected_release" \
  MINIMUM_STARTED_AT="$minimum_started_at" \
    /usr/bin/python3 -I -c '
import json
import os
from datetime import datetime, timezone

payload = json.loads(os.environ["HEALTH_PAYLOAD"])
roulette_id = payload.get("roulette_id")
if roulette_id != os.environ["EXPECTED_ROULETTE"]:
    raise SystemExit(1)
if payload.get("config_fingerprint") != os.environ["EXPECTED_FINGERPRINT"]:
    raise SystemExit(1)
if payload.get("release_id") != os.environ["EXPECTED_RELEASE"]:
    raise SystemExit(1)
if payload.get("status") != "healthy":
    raise SystemExit(1)
if payload.get("fresh") is not True or payload.get("ws_connected") is not True:
    raise SystemExit(1)
minimum = int(os.environ["MINIMUM_STARTED_AT"])
if minimum:
    started = datetime.fromisoformat(str(payload.get("worker_started_at", "")).replace("Z", "+00:00"))
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    if started.timestamp() + 1 < minimum:
        raise SystemExit(1)
'
}

heartbeat_is_fresh() {
  BEHAVIOR_REDIS_URL="$redis_url" \
  BEHAVIOR_HEALTH_KEY="$health_key" \
  BEHAVIOR_HEARTBEAT_MAX_AGE="$heartbeat_max_age" \
  EXPECTED_FINGERPRINT="$expected_fingerprint" \
  EXPECTED_RELEASE="$expected_release" \
  MINIMUM_STARTED_AT="$minimum_started_at" \
    sudo -u "$runtime_user" \
      --preserve-env=BEHAVIOR_REDIS_URL,BEHAVIOR_HEALTH_KEY,BEHAVIOR_HEARTBEAT_MAX_AGE,EXPECTED_FINGERPRINT,EXPECTED_RELEASE,MINIMUM_STARTED_AT \
      "$api_root/.venv/bin/python" -I -c '
import json
import os
from datetime import datetime, timezone

from redis import Redis

client = Redis.from_url(
    os.environ["BEHAVIOR_REDIS_URL"],
    socket_connect_timeout=3,
    socket_timeout=3,
)
raw = client.get(os.environ["BEHAVIOR_HEALTH_KEY"])
if not raw:
    raise SystemExit(1)
payload = json.loads(raw)
if payload.get("config_fingerprint") != os.environ["EXPECTED_FINGERPRINT"]:
    raise SystemExit(1)
if payload.get("release_id") != os.environ["EXPECTED_RELEASE"]:
    raise SystemExit(1)
if payload.get("status") != "healthy" or payload.get("ws_connected") is not True:
    raise SystemExit(1)
minimum = int(os.environ["MINIMUM_STARTED_AT"])
if minimum:
    started = datetime.fromisoformat(str(payload.get("worker_started_at", "")).replace("Z", "+00:00"))
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    if started.timestamp() + 1 < minimum:
        raise SystemExit(1)
heartbeat_at = payload.get("heartbeat_at")
if not heartbeat_at:
    raise SystemExit(1)
if isinstance(heartbeat_at, (int, float)):
    heartbeat = datetime.fromtimestamp(float(heartbeat_at), tz=timezone.utc)
else:
    heartbeat = datetime.fromisoformat(str(heartbeat_at).replace("Z", "+00:00"))
    if heartbeat.tzinfo is None:
        heartbeat = heartbeat.replace(tzinfo=timezone.utc)
age = (datetime.now(timezone.utc) - heartbeat.astimezone(timezone.utc)).total_seconds()
max_age = int(os.environ["BEHAVIOR_HEARTBEAT_MAX_AGE"])
if age < -30 or age > max_age:
    raise SystemExit(1)
'
}

for ((attempt = 1; attempt <= attempts; attempt++)); do
  history_payload="$(
    curl -fsS --max-time 5 -H 'Accept: application/json' \
      "$base_url/history/$slug?limit=1" 2>/dev/null || true
  )"
  health_payload="$(
    curl -fsS --max-time 5 -H 'Accept: application/json' \
      "$base_url/api/patterns/behavior-lab/health" 2>/dev/null || true
  )"

  if [[ "$history_payload" == *'"results"'* ]] \
      && [[ "$history_payload" == *'"items"'* ]] \
      && [[ -n "$health_payload" ]] \
      && route_payload_is_valid "$health_payload" >/dev/null 2>&1 \
      && worker_is_online \
      && heartbeat_is_fresh >/dev/null 2>&1; then
    printf '%s\n' "$health_payload"
    exit 0
  fi

  if (( attempt < attempts )); then
    sleep "$interval"
  fi
done

echo "API ou worker Behavior Lab nao ficaram saudaveis apos $attempts tentativas." >&2
exit 1

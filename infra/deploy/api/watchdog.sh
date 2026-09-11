#!/usr/bin/env bash
set -euo pipefail

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
unset CDPATH ENV BASH_ENV PYTHONHOME PYTHONPATH

base_dir="/var/www/revesbot"
runtime_user="revesbot"
trusted_root="/var/lib/revesbot-api-deploy"
state_dir="$trusted_root/watchdog"
state_file="$state_dir/failures"
restart_state_file="$state_dir/last-restart"
deploy_lock_file="$trusted_root/deploy.lock"
api_process_name="revesbot-api"
behavior_process_name="revesbot-behavior-lab"
max_failures="${API_WATCHDOG_FAILURES:-2}"
restart_cooldown="${API_WATCHDOG_RESTART_COOLDOWN_SECONDS:-900}"
base_url="http://127.0.0.1:8082"
env_file="/etc/revesbot/api.env"

[[ "$max_failures" =~ ^[1-9][0-9]*$ ]] || {
  echo "API_WATCHDOG_FAILURES invalido." >&2
  exit 2
}
[[ "$restart_cooldown" =~ ^[1-9][0-9]*$ ]] || {
  echo "API_WATCHDOG_RESTART_COOLDOWN_SECONDS invalido." >&2
  exit 2
}

install -d -m 0700 -o root -g root "$trusted_root" "$state_dir"
exec 8>"$deploy_lock_file"
if ! flock -n 8; then
  logger -t revesbot-api-watchdog "check skipped during API deploy"
  exit 0
fi

pm2_api() {
  sudo -u "$runtime_user" env PM2_HOME="/home/$runtime_user/.pm2" pm2 "$@"
}

process_is_online() {
  local process_name="$1"
  local process_pid
  process_pid="$(pm2_api pid "$process_name" 2>/dev/null | awk 'NF { print $1; exit }')"
  [[ "$process_pid" =~ ^[1-9][0-9]*$ ]]
}

root_secret_file_is_safe() {
  local candidate="$1"
  SECRET_FILE="$candidate" /usr/bin/python3 -I -c '
import os
import pathlib
import stat

path = pathlib.Path(os.environ["SECRET_FILE"])
metadata = path.lstat()
if not stat.S_ISREG(metadata.st_mode):
    raise SystemExit(1)
if metadata.st_uid != 0 or metadata.st_mode & 0o022:
    raise SystemExit(1)
parent = path.parent.stat()
if parent.st_uid != 0 or parent.st_mode & 0o022:
    raise SystemExit(1)
'
}

sealed_active_release() {
  local candidate
  candidate="$(readlink -f "$base_dir/api-current" 2>/dev/null || true)"
  [[ -n "$candidate" ]] || return 1
  RELEASE_CANDIDATE="$candidate" BASE_DIR="$base_dir" /usr/bin/python3 -I -c '
import os
import pathlib
import stat

base = pathlib.Path(os.environ["BASE_DIR"]).resolve(strict=True)
releases = (base / "api-releases").resolve(strict=True)
release = pathlib.Path(os.environ["RELEASE_CANDIDATE"]).resolve(strict=True)
if release.parent != releases or len(release.name) != 40:
    raise SystemExit(1)
if any(character not in "0123456789abcdef" for character in release.name):
    raise SystemExit(1)
for protected in (base, releases, release):
    metadata = protected.stat()
    if metadata.st_uid != 0 or metadata.st_mode & 0o022:
        raise SystemExit(1)
marker = release / ".release-commit"
config = release / "infra" / "pm2" / "api-minimal.config.js"
for regular in (marker, config):
    metadata = regular.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise SystemExit(1)
    if metadata.st_uid != 0 or metadata.st_mode & 0o022:
        raise SystemExit(1)
if marker.read_text(encoding="utf-8").strip() != release.name:
    raise SystemExit(1)
print(release)
'
}

recover_sealed_release() {
  local active_release
  active_release="$(sealed_active_release)" || return 1
  [[ -s "$env_file" ]] || return 1
  root_secret_file_is_safe "$env_file" || return 1

  set -a
  # shellcheck disable=SC1090
  source "$env_file"
  set +a
  : "${MONGO_URL:?MONGO_URL nao configurada}"
  : "${PIXGO_MONGO_URL:?PIXGO_MONGO_URL nao configurada}"
  : "${REDIS_CONNECT:?REDIS_CONNECT nao configurada}"
  : "${PIXGO_API_KEY:?PIXGO_API_KEY nao configurada}"
  : "${PIXGO_WEBHOOK_SECRET:?PIXGO_WEBHOOK_SECRET nao configurada}"

  sudo -u "$runtime_user" \
    --preserve-env=API_PORT,API_WORKERS,MONGO_URL,MONGO_DATABASE,PIXGO_MONGO_URL,PIXGO_MONGO_DATABASE,REDIS_CONNECT,PIXGO_API_KEY,PIXGO_WEBHOOK_SECRET,PIXGO_BASE_URL,BEHAVIOR_LAB_HEARTBEAT_MAX_AGE_SECONDS,BEHAVIOR_LAB_RECONCILE_INTERVAL_SECONDS,BEHAVIOR_LAB_LOG_LEVEL \
    env PM2_HOME="/home/$runtime_user/.pm2" \
    REVESBOT_API_CURRENT="$base_dir/api-current" \
    pm2 startOrReload \
      "$active_release/infra/pm2/api-minimal.config.js" \
      --update-env
  pm2_api save >/dev/null
}

behavior_health_is_valid() {
  local payload="$1"
  local expected_release="$2"
  printf '%s' "$payload" | EXPECTED_RELEASE="$expected_release" /usr/bin/python3 -I -c '
import json
import os
import sys

payload = json.load(sys.stdin)
valid = (
    payload.get("status") == "healthy"
    and payload.get("fresh") is True
    and payload.get("ws_connected") is True
    and payload.get("release_id") == os.environ["EXPECTED_RELEASE"]
)
raise SystemExit(0 if valid else 1)
'
}

api_is_healthy() {
  local behavior_body
  local behavior_response
  local behavior_status
  local expected_release
  local history_payload
  history_payload="$(
    curl -fsS --max-time 5 -H 'Accept: application/json' \
      "$base_url/history/pragmatic-auto-roulette?limit=1" 2>/dev/null || true
  )"
  [[ "$history_payload" == *'"results"'* ]] || return 1
  [[ "$history_payload" == *'"items"'* ]] || return 1
  process_is_online "$api_process_name" || return 1
  behavior_response="$(
    curl -sS --max-time 5 -H 'Accept: application/json' \
      -w $'\n%{http_code}' \
      "$base_url/api/patterns/behavior-lab/health"
  )" || return 1
  behavior_status="${behavior_response##*$'\n'}"
  behavior_body="${behavior_response%$'\n'*}"
  if [[ "$behavior_status" == "404" ]]; then
    # A rota inexiste legitimamente apenas antes da primeira release selada do
    # laboratório. Em uma release nova, 404 indica API antiga ou cutover
    # incompleto e deve acionar a recuperação conjunta.
    sealed_active_release >/dev/null 2>&1 && return 1
    return 0
  fi
  [[ "$behavior_status" == "200" ]] || return 1
  process_is_online "$behavior_process_name" || return 1
  expected_release="$(basename "$(readlink -f "$base_dir/api-current")")"
  behavior_health_is_valid "$behavior_body" "$expected_release" || return 1
}

if api_is_healthy >/dev/null 2>&1; then
  printf '0\n' > "$state_file"
  exit 0
fi

failures=0
[[ -f "$state_file" ]] && read -r failures < "$state_file" || true
[[ "$failures" =~ ^[0-9]+$ ]] || failures=0
failures=$((failures + 1))
printf '%s\n' "$failures" > "$state_file"
logger -t revesbot-api-watchdog "health failure $failures/$max_failures"

if (( failures >= max_failures )); then
  current_epoch="$(date +%s)"
  last_restart_epoch=0
  [[ -f "$restart_state_file" ]] && read -r last_restart_epoch < "$restart_state_file" || true
  [[ "$last_restart_epoch" =~ ^[0-9]+$ ]] || last_restart_epoch=0
  if (( current_epoch - last_restart_epoch >= restart_cooldown )); then
    if sealed_active_release >/dev/null 2>&1; then
      # Um release selado e imutavel pode recriar inclusive um processo PM2
      # removido. Releases legados continuam limitados a restart de processos
      # ja registrados, sem executar configuracao gravavel pelo runtime.
      recover_sealed_release
    else
      process_names=("$api_process_name")
      if pm2_api describe "$behavior_process_name" >/dev/null 2>&1; then
        process_names+=("$behavior_process_name")
      fi
      pm2_api restart "${process_names[@]}"
    fi
    printf '%s\n' "$current_epoch" > "$restart_state_file"
  else
    logger -t revesbot-api-watchdog \
      "restart suppressed during ${restart_cooldown}s cooldown"
  fi
  printf '0\n' > "$state_file"
fi

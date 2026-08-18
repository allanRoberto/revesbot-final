#!/usr/bin/env bash
set -euo pipefail

base_dir="${REVESBOT_BASE_DIR:-/var/www/revesbot}"
env_file="${COLLECTOR_ENV_FILE:-/etc/revesbot/collector.env}"
state_file="$base_dir/shared/state/watchdog.failures"
health_url="${COLLECTOR_HEALTH_URL:-http://127.0.0.1:9101/health/ready}"
process_name="${COLLECTOR_PROCESS_NAME:-collector-pragmatic-test}"
max_failures="${COLLECTOR_EXTERNAL_WATCHDOG_FAILURES:-2}"

if [[ -f "$env_file" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$env_file"
  set +a
fi

response="$(curl -sS --max-time 5 "$health_url" 2>/dev/null || true)"
if [[ "$response" == *'"status": "ready"'* ]]; then
  printf '0\n' > "$state_file"
  exit 0
fi

# Disconnection alone is handled by the collector reconnect loop. Restart on
# a dead endpoint or when freshness/dependency checks explicitly fail.
if [[ -n "$response" ]] \
  && [[ "$response" != *"websocket_stale"* ]] \
  && [[ "$response" != *"results_stale"* ]] \
  && [[ "$response" != *"mongo_unavailable"* ]] \
  && [[ "$response" != *"redis_unavailable"* ]]; then
  exit 0
fi

failures=0
if [[ -f "$state_file" ]]; then
  read -r failures < "$state_file" || failures=0
fi
failures=$((failures + 1))
printf '%s\n' "$failures" > "$state_file"
logger -t revesbot-collector-watchdog "health failure $failures/$max_failures: ${response:-endpoint unavailable}"

if (( failures >= max_failures )); then
  sudo -u revesbot env PM2_HOME=/home/revesbot/.pm2 pm2 restart "$process_name" --update-env
  printf '0\n' > "$state_file"
fi

#!/usr/bin/env bash
set -euo pipefail

state_file=/var/www/revesbot/shared/state/api-watchdog-failures
process_name=revesbot-api
max_failures="${API_WATCHDOG_FAILURES:-2}"

if API_HEALTH_BASE_URL=http://127.0.0.1:8082 HEALTHCHECK_ATTEMPTS=1 \
    /var/www/revesbot/api-current/infra/deploy/api/healthcheck.sh >/dev/null 2>&1; then
  printf '0\n' > "$state_file"
  exit 0
fi

failures=0
[[ -f "$state_file" ]] && read -r failures < "$state_file" || true
failures=$((failures + 1))
printf '%s\n' "$failures" > "$state_file"
logger -t revesbot-api-watchdog "health failure $failures/$max_failures"

if (( failures >= max_failures )); then
  sudo -u revesbot env PM2_HOME=/home/revesbot/.pm2 pm2 restart "$process_name" --update-env
  printf '0\n' > "$state_file"
fi

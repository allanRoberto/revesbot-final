#!/usr/bin/env bash
set -euo pipefail

state_dir=/var/www/revesbot/shared/state
state_file="$state_dir/patterns-watchdog-failures"
max_failures="${PATTERNS_WATCHDOG_FAILURES:-2}"

install -d -m 0755 -o revesbot -g revesbot "$state_dir"

if HEALTHCHECK_ATTEMPTS=1 \
    /var/www/revesbot/patterns-current/infra/deploy/patterns/healthcheck.sh \
    >/dev/null 2>&1; then
  printf '0\n' > "$state_file"
  chown revesbot:revesbot "$state_file"
  exit 0
fi

failures=0
[[ -f "$state_file" ]] && read -r failures < "$state_file" || true
failures=$((failures + 1))
printf '%s\n' "$failures" > "$state_file"
chown revesbot:revesbot "$state_file"
logger -t revesbot-patterns-watchdog "health failure $failures/$max_failures"

if (( failures >= max_failures )); then
  sudo -u revesbot env PM2_HOME=/home/revesbot/.pm2 \
    pm2 restart pattern-nera-prod pattern-last-hope-prod
  printf '0\n' > "$state_file"
  chown revesbot:revesbot "$state_file"
fi

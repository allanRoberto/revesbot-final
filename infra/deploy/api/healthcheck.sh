#!/usr/bin/env bash
set -euo pipefail

base_url="${API_HEALTH_BASE_URL:-http://127.0.0.1:8082}"
slug="${API_HEALTH_SLUG:-pragmatic-auto-roulette}"
attempts="${HEALTHCHECK_ATTEMPTS:-24}"
interval="${HEALTHCHECK_INTERVAL_SECONDS:-5}"
api_root="${REVESBOT_API_CURRENT:-/var/www/revesbot/api-current}"
env_file="${API_ENV_FILE:-/etc/revesbot/api.env}"

set -a
# shellcheck disable=SC1090
source "$env_file"
set +a

for ((attempt = 1; attempt <= attempts; attempt++)); do
  if PYTHONPATH="$api_root/apps" "$api_root/.venv/bin/python" -c \
      'import asyncio; from api.core.redis_client import r; from api.core.runtime_db import ping_runtime_dependencies; asyncio.run(ping_runtime_dependencies()); asyncio.run(r.ping())' \
      >/dev/null 2>&1 \
      && payload="$(curl -fsS --max-time 5 -H 'Accept: application/json' "$base_url/history/$slug?limit=1" 2>/dev/null)" \
      && [[ "$payload" == *'"results"'* ]] \
      && [[ "$payload" == *'"items"'* ]]; then
    printf '%s\n' "$payload"
    exit 0
  fi
  sleep "$interval"
done

echo "API ou dependencias nao ficaram prontas em $((attempts * interval)) segundos." >&2
exit 1

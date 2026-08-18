#!/usr/bin/env bash
set -euo pipefail

base_url="${API_HEALTH_BASE_URL:-http://127.0.0.1:8082}"
slug="${API_HEALTH_SLUG:-pragmatic-auto-roulette}"
attempts="${HEALTHCHECK_ATTEMPTS:-24}"
interval="${HEALTHCHECK_INTERVAL_SECONDS:-5}"

for ((attempt = 1; attempt <= attempts; attempt++)); do
  if payload="$(curl -fsS --max-time 5 -H 'Accept: application/json' "$base_url/history/$slug?limit=1" 2>/dev/null)" \
      && [[ "$payload" == *'"results"'* ]] \
      && [[ "$payload" == *'"items"'* ]]; then
    printf '%s\n' "$payload"
    exit 0
  fi
  sleep "$interval"
done

echo "API nao ficou pronta em $((attempts * interval)) segundos." >&2
exit 1

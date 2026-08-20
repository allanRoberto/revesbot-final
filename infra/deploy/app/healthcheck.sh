#!/usr/bin/env bash
set -euo pipefail

base_url="${APP_HEALTH_BASE_URL:-http://127.0.0.1:3002}"
attempts="${HEALTHCHECK_ATTEMPTS:-30}"
interval="${HEALTHCHECK_INTERVAL_SECONDS:-3}"

for ((attempt = 1; attempt <= attempts; attempt++)); do
  if payload="$(curl -fsS --max-time 5 "$base_url/api/health" 2>/dev/null)" \
      && [[ "$payload" == *'"status":"ok"'* ]] \
      && [[ "$payload" == *'"mongo":true'* ]] \
      && [[ "$payload" == *'"auth":true'* ]]; then
    printf '%s\n' "$payload"
    exit 0
  fi
  sleep "$interval"
done

echo "App nao ficou saudavel em $((attempts * interval)) segundos." >&2
exit 1

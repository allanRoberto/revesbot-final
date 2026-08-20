#!/usr/bin/env bash
set -euo pipefail

base_url="${AUTH_HEALTH_BASE_URL:-http://127.0.0.1:3090}"
attempts="${HEALTHCHECK_ATTEMPTS:-20}"
interval="${HEALTHCHECK_INTERVAL_SECONDS:-3}"

for ((attempt = 1; attempt <= attempts; attempt++)); do
  if payload="$(curl -fsS --max-time 5 "$base_url/health" 2>/dev/null)" \
      && [[ "$payload" == *'"status":"ok"'* ]] \
      && [[ "$payload" == *'"service":"auth-api"'* ]]; then
    printf '%s\n' "$payload"
    exit 0
  fi
  sleep "$interval"
done

echo "Auth nao ficou saudavel em $((attempts * interval)) segundos." >&2
exit 1

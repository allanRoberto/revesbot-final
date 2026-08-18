#!/usr/bin/env bash
set -euo pipefail

health_url="${COLLECTOR_HEALTH_URL:-http://127.0.0.1:9101/health/ready}"
attempts="${HEALTHCHECK_ATTEMPTS:-24}"
interval="${HEALTHCHECK_INTERVAL_SECONDS:-5}"

for ((attempt = 1; attempt <= attempts; attempt++)); do
  if response="$(curl -fsS --max-time 4 "$health_url" 2>/dev/null)"; then
    printf '%s\n' "$response"
    exit 0
  fi
  sleep "$interval"
done

echo "Collector nao ficou pronto em $((attempts * interval)) segundos." >&2
exit 1

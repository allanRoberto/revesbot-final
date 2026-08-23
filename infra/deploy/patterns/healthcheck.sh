#!/usr/bin/env bash
set -euo pipefail

base_dir="${REVESBOT_BASE_DIR:-/var/www/revesbot}"
runtime_user="${REVESBOT_RUNTIME_USER:-revesbot}"
env_file="${PATTERNS_ENV_FILE:-/etc/revesbot/patterns.env}"
attempts="${HEALTHCHECK_ATTEMPTS:-24}"
interval="${HEALTHCHECK_INTERVAL_SECONDS:-5}"
current_root="$(readlink -f "$base_dir/patterns-current" 2>/dev/null || true)"

test -n "$current_root"
test -d "$current_root"
test -s "$env_file"

set -a
# shellcheck disable=SC1090
source "$env_file"
set +a

for ((attempt = 1; attempt <= attempts; attempt++)); do
  if sudo -u "$runtime_user" --preserve-env=MONGO_URL,MONGO_DATABASE,MONGO_DB,MONGO_TLS \
      env PYTHONPATH="$current_root" "$current_root/.venv/bin/python" \
      -m apps.monitoring.patterns.healthcheck; then
    exit 0
  fi
  sleep "$interval"
done

echo "Patterns nao ficaram saudaveis em $((attempts * interval)) segundos." >&2
exit 1

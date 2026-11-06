#!/usr/bin/env bash
set -euo pipefail

request="${SSH_ORIGINAL_COMMAND:-}"
if [[ "$request" == "restore-vector-experiments-routes" ]]; then
  exec sudo /usr/local/sbin/revesbot-api-deploy "$request"
fi

if [[ ! "$request" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Comando de deploy invalido." >&2
  exit 2
fi

exec sudo /usr/local/sbin/revesbot-api-deploy "$request"

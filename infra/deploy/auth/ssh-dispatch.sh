#!/usr/bin/env bash
set -euo pipefail

commit_sha="${SSH_ORIGINAL_COMMAND:-}"
if [[ ! "$commit_sha" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Comando de deploy invalido." >&2
  exit 2
fi

exec sudo /usr/local/sbin/revesbot-auth-deploy "$commit_sha"

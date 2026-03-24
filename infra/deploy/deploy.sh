#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 <develop|main> [repo_dir]" >&2
  exit 1
}

stage="${1:-}"
repo_dir="${2:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"

if [[ "$stage" != "develop" && "$stage" != "main" ]]; then
  usage
fi

branch="$stage"
env_file="${ENV_FILE:-/etc/revesbot/${stage}.env}"
venv_dir="${VENV_DIR:-$repo_dir/.venv}"
api_dir="$repo_dir/apps/api"
auth_dir="$repo_dir/apps/auth_api"
pm2_config="$repo_dir/infra/pm2/ecosystem.config.js"
python_cmd="${PYTHON_CMD:-python3}"
npm_cache_dir="${NPM_CACHE_DIR:-/var/cache/npm/revesbot-auth-api}"
puppeteer_cache_dir="${PUPPETEER_CACHE_DIR:-/var/cache/puppeteer}"

if [[ ! -d "$repo_dir/.git" ]]; then
  echo "Repository not found: $repo_dir" >&2
  exit 1
fi

if [[ ! -f "$env_file" ]]; then
  echo "Missing env file: $env_file" >&2
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "git is required on the server" >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required on the server" >&2
  exit 1
fi

if ! command -v pm2 >/dev/null 2>&1; then
  echo "pm2 is required on the server" >&2
  exit 1
fi

if ! "$python_cmd" --version >/dev/null 2>&1; then
  echo "Python command is not available: $python_cmd" >&2
  exit 1
fi

echo "==> Loading environment from $env_file"
set -a
source "$env_file"
set +a

echo "==> Updating checkout for branch $branch"
cd "$repo_dir"
git fetch origin "$branch"

if git show-ref --verify --quiet "refs/heads/$branch"; then
  git checkout "$branch"
else
  git checkout -b "$branch" "origin/$branch"
fi

git reset --hard "origin/$branch"

echo "==> Preparing Python environment"
if [[ ! -x "$venv_dir/bin/python" ]]; then
  "$python_cmd" -m venv "$venv_dir"
fi

"$venv_dir/bin/pip" install --upgrade pip
"$venv_dir/bin/pip" install -r "$api_dir/requirements.txt"

echo "==> Installing auth_api dependencies"
cd "$auth_dir"
mkdir -p "$npm_cache_dir" "$puppeteer_cache_dir"
export PUPPETEER_CACHE_DIR="$puppeteer_cache_dir"
npm ci --cache "$npm_cache_dir"
npm run build

if [[ "$stage" == "develop" ]]; then
  api_process="api-dev"
  auth_process="auth-api-dev"
else
  api_process="api-prod"
  auth_process="auth-api-prod"
fi

echo "==> Reloading PM2 processes: $api_process, $auth_process"
cd "$repo_dir"
export DEPLOY_STAGE="$stage"
export REPO_ROOT="$repo_dir"
export PYTHON_BIN="$venv_dir/bin/python"
pm2 startOrReload "$pm2_config" --only "$api_process" --update-env
pm2 startOrReload "$pm2_config" --only "$auth_process" --update-env
pm2 save

echo "==> Deploy completed for $stage"

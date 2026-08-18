#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Execute via sudo." >&2
  exit 1
fi

commit_sha="${1:-}"
[[ "$commit_sha" =~ ^[0-9a-f]{40}$ ]] || { echo "Informe o SHA Git completo." >&2; exit 1; }

base_dir="${REVESBOT_BASE_DIR:-/var/www/revesbot}"
runtime_user="${REVESBOT_RUNTIME_USER:-revesbot}"
deploy_ref="${DEPLOY_REF:-main}"
repository="$base_dir/repository"
release_dir="$base_dir/api-releases/$commit_sha"
env_file="${API_ENV_FILE:-/etc/revesbot/api.env}"
lock_file="$base_dir/shared/api-deploy.lock"
previous_target="$(readlink -f "$base_dir/api-current" 2>/dev/null || true)"

exec 9>"$lock_file"
flock -n 9 || { echo "Outro deploy da API esta em andamento." >&2; exit 1; }
test -d "$repository/.git"
test -s "$env_file"

sudo -u "$runtime_user" git -C "$repository" fetch --prune origin "$deploy_ref"
if ! sudo -u "$runtime_user" git -C "$repository" cat-file -e "$commit_sha^{commit}" 2>/dev/null; then
  sudo -u "$runtime_user" git -C "$repository" fetch origin "$commit_sha"
fi
sudo -u "$runtime_user" git -C "$repository" cat-file -e "$commit_sha^{commit}"

if [[ ! -d "$release_dir" ]]; then
  sudo -u "$runtime_user" git -C "$repository" worktree add --detach "$release_dir" "$commit_sha"
fi

sudo -u "$runtime_user" python3 -m venv "$release_dir/.venv"
sudo -u "$runtime_user" "$release_dir/.venv/bin/pip" install --disable-pip-version-check \
  -r "$release_dir/apps/api/requirements-minimal.txt" pytest

cd "$release_dir"
sudo -u "$runtime_user" env PYTHONPATH=apps "$release_dir/.venv/bin/python" -m pytest -q \
  apps/api/tests/test_roulette_history_route.py \
  apps/api/tests/test_results_websocket.py \
  apps/api/tests/test_minimal_api.py \
  apps/api/tests/test_pixgo_webhook.py

set -a
# shellcheck disable=SC1090
source "$env_file"
set +a
: "${MONGO_URL:?MONGO_URL nao configurada}"
: "${PIXGO_MONGO_URL:?PIXGO_MONGO_URL nao configurada}"
: "${REDIS_CONNECT:?REDIS_CONNECT nao configurada}"
: "${PIXGO_API_KEY:?PIXGO_API_KEY nao configurada}"
: "${PIXGO_WEBHOOK_SECRET:?PIXGO_WEBHOOK_SECRET nao configurada}"

sudo -u "$runtime_user" --preserve-env=MONGO_URL,MONGO_DATABASE,PIXGO_MONGO_URL,PIXGO_MONGO_DATABASE \
  env PYTHONPATH="$release_dir/apps" "$release_dir/.venv/bin/python" -c \
  'import asyncio; from api.core.runtime_db import ping_runtime_dependencies; asyncio.run(ping_runtime_dependencies()); print("databases-ok")'

ln -sfn "$release_dir" "$base_dir/api-current.next"
mv -Tf "$base_dir/api-current.next" "$base_dir/api-current"
chown -h "$runtime_user:$runtime_user" "$base_dir/api-current"

install -m 0644 "$base_dir/api-current/infra/systemd/revesbot-api-watchdog.service" /etc/systemd/system/
install -m 0644 "$base_dir/api-current/infra/systemd/revesbot-api-watchdog.timer" /etc/systemd/system/
install -m 0644 "$base_dir/api-current/infra/logrotate/revesbot-api" /etc/logrotate.d/revesbot-api
systemctl daemon-reload
systemctl enable --now revesbot-api-watchdog.timer

if ! sudo -u "$runtime_user" --preserve-env \
    env PM2_HOME="/home/$runtime_user/.pm2" REVESBOT_API_CURRENT="$base_dir/api-current" \
    pm2 startOrReload "$base_dir/api-current/infra/pm2/api-minimal.config.js" --update-env; then
  [[ -n "$previous_target" ]] && ln -sfn "$previous_target" "$base_dir/api-current"
  exit 1
fi

if ! "$base_dir/api-current/infra/deploy/api/healthcheck.sh"; then
  if [[ -n "$previous_target" && -d "$previous_target" ]]; then
    ln -sfn "$previous_target" "$base_dir/api-current"
    sudo -u "$runtime_user" --preserve-env \
      env PM2_HOME="/home/$runtime_user/.pm2" REVESBOT_API_CURRENT="$base_dir/api-current" \
      pm2 startOrReload "$base_dir/api-current/infra/pm2/api-minimal.config.js" --update-env
  fi
  echo "Deploy revertido porque a API nao ficou saudavel." >&2
  exit 1
fi

sudo -u "$runtime_user" env PM2_HOME="/home/$runtime_user/.pm2" pm2 save

mapfile -t old_releases < <(find "$base_dir/api-releases" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -nr | tail -n +4 | cut -d' ' -f2-)
for old_release in "${old_releases[@]}"; do
  [[ "$old_release" == "$(readlink -f "$base_dir/api-current")" ]] && continue
  sudo -u "$runtime_user" git -C "$repository" worktree remove --force "$old_release" || true
done

# Atualiza os executáveis estáveis somente depois que este deploy terminou.
install -m 0755 "$base_dir/api-current/infra/deploy/api/deploy.sh" \
  /usr/local/sbin/revesbot-api-deploy.next
mv -f /usr/local/sbin/revesbot-api-deploy.next /usr/local/sbin/revesbot-api-deploy
install -m 0755 "$base_dir/api-current/infra/deploy/api/ssh-dispatch.sh" \
  /usr/local/sbin/revesbot-api-deploy-dispatch

echo "API implantada no commit $commit_sha"

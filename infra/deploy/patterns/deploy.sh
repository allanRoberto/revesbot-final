#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Execute via sudo." >&2
  exit 1
fi

commit_sha="${1:-}"
[[ "$commit_sha" =~ ^[0-9a-f]{40}$ ]] || {
  echo "Informe o SHA Git completo." >&2
  exit 1
}

base_dir="${REVESBOT_BASE_DIR:-/var/www/revesbot}"
runtime_user="${REVESBOT_RUNTIME_USER:-revesbot}"
deploy_ref="${DEPLOY_REF:-main}"
repository="$base_dir/repository"
releases_dir="$base_dir/pattern-releases"
release_dir="$releases_dir/$commit_sha"
env_file="${PATTERNS_ENV_FILE:-/etc/revesbot/patterns.env}"
lock_file="$base_dir/shared/patterns-deploy.lock"
previous_target="$(readlink -f "$base_dir/patterns-current" 2>/dev/null || true)"

[[ "$base_dir" == /var/www/revesbot || "$base_dir" == /var/www/revesbot/* ]] || {
  echo "REVESBOT_BASE_DIR fora do escopo permitido." >&2
  exit 1
}
test -d "$repository/.git"
test -s "$env_file"
install -d -m 0755 -o "$runtime_user" -g "$runtime_user" "$releases_dir"
install -d -m 0755 -o "$runtime_user" -g "$runtime_user" "$base_dir/shared"

exec 9>"$lock_file"
flock -n 9 || { echo "Outro deploy de patterns esta em andamento." >&2; exit 1; }

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
  -r "$release_dir/apps/monitoring/requirements-patterns-dev.txt"

cd "$release_dir"
sudo -u "$runtime_user" env PYTHONPATH="$release_dir" \
  "$release_dir/.venv/bin/python" -m pytest -q \
  apps/monitoring/tests/test_pattern_platform.py
sudo -u "$runtime_user" env PYTHONPATH="$release_dir" \
  "$release_dir/.venv/bin/python" -m compileall -q apps/monitoring/patterns

set -a
# shellcheck disable=SC1090
source "$env_file"
set +a
: "${MONGO_URL:?MONGO_URL nao configurada}"
: "${REDIS_CONNECT:?REDIS_CONNECT nao configurada}"

sudo -u "$runtime_user" --preserve-env=MONGO_URL,MONGO_DATABASE,MONGO_DB,MONGO_TLS \
  env PYTHONPATH="$release_dir" "$release_dir/.venv/bin/python" -c \
  'import os; from pymongo import MongoClient; from apps.monitoring.patterns.__main__ import _mongo_kwargs; url=os.environ["MONGO_URL"]; MongoClient(url, serverSelectionTimeoutMS=5000, **_mongo_kwargs(url)).admin.command("ping"); print("mongodb-ok")'

ln -sfn "$release_dir" "$base_dir/patterns-current.next"
mv -Tf "$base_dir/patterns-current.next" "$base_dir/patterns-current"
chown -h "$runtime_user:$runtime_user" "$base_dir/patterns-current"

install -m 0644 "$base_dir/patterns-current/infra/systemd/revesbot-patterns-watchdog.service" \
  /etc/systemd/system/revesbot-patterns-watchdog.service
install -m 0644 "$base_dir/patterns-current/infra/systemd/revesbot-patterns-watchdog.timer" \
  /etc/systemd/system/revesbot-patterns-watchdog.timer
install -m 0644 "$base_dir/patterns-current/infra/logrotate/revesbot-patterns" \
  /etc/logrotate.d/revesbot-patterns
systemctl daemon-reload
systemctl enable --now revesbot-patterns-watchdog.timer

reload_patterns() {
  sudo -u "$runtime_user" --preserve-env \
    env PM2_HOME="/home/$runtime_user/.pm2" \
    REVESBOT_PATTERNS_CURRENT="$base_dir/patterns-current" \
    pm2 startOrReload "$base_dir/patterns-current/infra/pm2/patterns.config.js" --update-env
}

if ! reload_patterns; then
  if [[ -n "$previous_target" && -d "$previous_target" ]]; then
    ln -sfn "$previous_target" "$base_dir/patterns-current"
  fi
  exit 1
fi

if ! "$base_dir/patterns-current/infra/deploy/patterns/healthcheck.sh"; then
  if [[ -n "$previous_target" && -d "$previous_target" ]]; then
    ln -sfn "$previous_target" "$base_dir/patterns-current"
    reload_patterns
  else
    sudo -u "$runtime_user" env PM2_HOME="/home/$runtime_user/.pm2" \
      pm2 stop pattern-nera-prod pattern-last-hope-prod || true
  fi
  echo "Deploy revertido porque os patterns nao ficaram saudaveis." >&2
  exit 1
fi

sudo -u "$runtime_user" env PM2_HOME="/home/$runtime_user/.pm2" pm2 save

install -m 0755 "$base_dir/patterns-current/infra/deploy/patterns/deploy.sh" \
  /usr/local/sbin/revesbot-patterns-deploy.next
mv -f /usr/local/sbin/revesbot-patterns-deploy.next \
  /usr/local/sbin/revesbot-patterns-deploy
install -m 0755 "$base_dir/patterns-current/infra/deploy/patterns/ssh-dispatch.sh" \
  /usr/local/sbin/revesbot-patterns-deploy-dispatch

mapfile -t old_releases < <(
  find "$releases_dir" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' \
    | sort -nr | tail -n +4 | cut -d' ' -f2-
)
for old_release in "${old_releases[@]}"; do
  resolved_old="$(readlink -f "$old_release" 2>/dev/null || true)"
  [[ -n "$resolved_old" ]] || continue
  [[ "$resolved_old" == "$releases_dir/"* ]] || {
    echo "Release antigo fora do diretorio esperado: $resolved_old" >&2
    exit 1
  }
  [[ "$resolved_old" == "$(readlink -f "$base_dir/patterns-current")" ]] && continue
  sudo -u "$runtime_user" git -C "$repository" worktree remove --force "$resolved_old"
done

echo "Patterns implantados no commit $commit_sha"

#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Execute via sudo." >&2
  exit 1
fi

commit_sha="${1:-}"
if [[ ! "$commit_sha" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Informe o SHA Git completo (40 caracteres)." >&2
  exit 1
fi

base_dir="${REVESBOT_BASE_DIR:-/var/www/revesbot}"
deploy_ref="${DEPLOY_REF:-main}"
runtime_user="${REVESBOT_RUNTIME_USER:-revesbot}"
repository="$base_dir/repository"
release_dir="$base_dir/releases/$commit_sha"
env_file="${COLLECTOR_ENV_FILE:-/etc/revesbot/collector.env}"
lock_file="$base_dir/shared/deploy.lock"
previous_target="$(readlink -f "$base_dir/current" 2>/dev/null || true)"

exec 9>"$lock_file"
flock -n 9 || { echo "Outro deploy esta em andamento." >&2; exit 1; }

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
  -r "$release_dir/apps/collector/requirements-dev.txt"
cd "$release_dir"
sudo -u "$runtime_user" "$release_dir/.venv/bin/python" -m pytest \
  apps/collector/tests -q

set -a
# shellcheck disable=SC1090
source "$env_file"
set +a
export REVESBOT_CURRENT="$base_dir/current"

cd "$release_dir/apps/collector"
sudo -u "$runtime_user" --preserve-env=MONGO_URL,REDIS_CONNECT,MONGO_DATABASE,MONGO_COLLECTION \
  "$release_dir/.venv/bin/python" -c \
  'from collector.config import CollectorSettings; CollectorSettings.from_env(); print("config-ok")'

ln -sfn "$release_dir" "$base_dir/current.next"
mv -Tf "$base_dir/current.next" "$base_dir/current"
chown -h "$runtime_user:$runtime_user" "$base_dir/current"

install -m 0644 "$base_dir/current/infra/systemd/revesbot-collector-watchdog.service" \
  /etc/systemd/system/revesbot-collector-watchdog.service
install -m 0644 "$base_dir/current/infra/systemd/revesbot-collector-watchdog.timer" \
  /etc/systemd/system/revesbot-collector-watchdog.timer
install -m 0644 "$base_dir/current/infra/systemd/revesbot-redis-tunnel.service" \
  /etc/systemd/system/revesbot-redis-tunnel.service
install -m 0644 "$base_dir/current/infra/logrotate/revesbot-collector" \
  /etc/logrotate.d/revesbot-collector
systemctl daemon-reload
systemctl enable --now revesbot-collector-watchdog.timer

if ! sudo -u "$runtime_user" --preserve-env \
  env PM2_HOME="/home/$runtime_user/.pm2" REVESBOT_CURRENT="$base_dir/current" \
  pm2 startOrReload "$base_dir/current/infra/pm2/collector.config.js" --update-env; then
  [[ -n "$previous_target" ]] && ln -sfn "$previous_target" "$base_dir/current"
  exit 1
fi

if ! "$base_dir/current/infra/deploy/collector/healthcheck.sh"; then
  if [[ -n "$previous_target" && -d "$previous_target" ]]; then
    ln -sfn "$previous_target" "$base_dir/current"
    sudo -u "$runtime_user" --preserve-env \
      env PM2_HOME="/home/$runtime_user/.pm2" REVESBOT_CURRENT="$base_dir/current" \
      pm2 startOrReload "$base_dir/current/infra/pm2/collector.config.js" --update-env
  fi
  echo "Deploy revertido porque o collector nao ficou saudavel." >&2
  exit 1
fi

sudo -u "$runtime_user" env PM2_HOME="/home/$runtime_user/.pm2" pm2 save

# On the first deploy PM2 is started by the CLI. Hand its daemon over to
# systemd so a server reboot exercises the same saved process list.
if ! systemctl is-active --quiet "pm2-$runtime_user"; then
  sudo -u "$runtime_user" env PM2_HOME="/home/$runtime_user/.pm2" pm2 kill
  systemctl reset-failed "pm2-$runtime_user"
  systemctl start "pm2-$runtime_user"
  "$base_dir/current/infra/deploy/collector/healthcheck.sh"
fi

# Retain the current release and the two previous releases.
mapfile -t old_releases < <(find "$base_dir/releases" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -nr | tail -n +4 | cut -d' ' -f2-)
for old_release in "${old_releases[@]}"; do
  [[ "$old_release" == "$(readlink -f "$base_dir/current")" ]] && continue
  sudo -u "$runtime_user" git -C "$repository" worktree remove --force "$old_release" || true
done

echo "Collector implantado no commit $commit_sha"

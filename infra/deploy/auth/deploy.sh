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
release_dir="$base_dir/auth-releases/$commit_sha"
env_file="${AUTH_ENV_FILE:-/etc/revesbot/auth.env}"
lock_file="$base_dir/shared/auth-deploy.lock"
previous_target="$(readlink -f "$base_dir/auth-current" 2>/dev/null || true)"
npm_cache="/var/cache/npm/revesbot-auth"

exec 9>"$lock_file"
flock -n 9 || { echo "Outro deploy do auth esta em andamento." >&2; exit 1; }
test -d "$repository/.git"
test -s "$env_file"

set -a
# shellcheck disable=SC1090
source "$env_file"
set +a
: "${APP_ORIGINS:?APP_ORIGINS nao configurado}"

sudo -H -u "$runtime_user" git -C "$repository" fetch --prune origin "$deploy_ref"
if ! sudo -H -u "$runtime_user" git -C "$repository" cat-file -e "$commit_sha^{commit}" 2>/dev/null; then
  sudo -H -u "$runtime_user" git -C "$repository" fetch origin "$commit_sha"
fi
sudo -H -u "$runtime_user" git -C "$repository" cat-file -e "$commit_sha^{commit}"

if [[ ! -d "$release_dir" ]]; then
  sudo -H -u "$runtime_user" git -C "$repository" worktree add --detach "$release_dir" "$commit_sha"
fi

sudo -H -u "$runtime_user" npm ci --prefix "$release_dir/apps/auth_api" --cache "$npm_cache"
sudo -H -u "$runtime_user" npm --prefix "$release_dir/apps/auth_api" run build

ln -sfn "$release_dir" "$base_dir/auth-current.next"
mv -Tf "$base_dir/auth-current.next" "$base_dir/auth-current"
chown -h "$runtime_user:$runtime_user" "$base_dir/auth-current"

pm2_config="$base_dir/auth-current/infra/pm2/auth-api.config.js"
if ! sudo -H -u "$runtime_user" --preserve-env \
    env PM2_HOME="/home/$runtime_user/.pm2" REVESBOT_AUTH_CURRENT="$base_dir/auth-current" \
    pm2 startOrReload "$pm2_config" --update-env; then
  [[ -n "$previous_target" ]] && ln -sfn "$previous_target" "$base_dir/auth-current"
  exit 1
fi

if ! "$base_dir/auth-current/infra/deploy/auth/healthcheck.sh"; then
  if [[ -n "$previous_target" && -d "$previous_target" ]]; then
    ln -sfn "$previous_target" "$base_dir/auth-current"
    sudo -H -u "$runtime_user" --preserve-env \
      env PM2_HOME="/home/$runtime_user/.pm2" REVESBOT_AUTH_CURRENT="$base_dir/auth-current" \
      pm2 startOrReload "$base_dir/auth-current/infra/pm2/auth-api.config.js" --update-env
  fi
  echo "Deploy revertido porque o auth nao ficou saudavel." >&2
  exit 1
fi

install -m 0644 "$base_dir/auth-current/infra/systemd/revesbot-auth-health.service" /etc/systemd/system/
install -m 0644 "$base_dir/auth-current/infra/systemd/revesbot-auth-health.timer" /etc/systemd/system/
install -m 0644 "$base_dir/auth-current/infra/logrotate/revesbot-auth" /etc/logrotate.d/revesbot-auth
systemctl daemon-reload
systemctl enable --now revesbot-auth-health.timer

sudo -H -u "$runtime_user" env PM2_HOME="/home/$runtime_user/.pm2" pm2 save

mapfile -t old_releases < <(find "$base_dir/auth-releases" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -nr | tail -n +4 | cut -d' ' -f2-)
for old_release in "${old_releases[@]}"; do
  [[ "$old_release" == "$(readlink -f "$base_dir/auth-current")" ]] && continue
  sudo -H -u "$runtime_user" git -C "$repository" worktree remove --force "$old_release" || true
done

install -m 0755 "$base_dir/auth-current/infra/deploy/auth/deploy.sh" /usr/local/sbin/revesbot-auth-deploy.next
mv -f /usr/local/sbin/revesbot-auth-deploy.next /usr/local/sbin/revesbot-auth-deploy
install -m 0755 "$base_dir/auth-current/infra/deploy/auth/ssh-dispatch.sh" /usr/local/sbin/revesbot-auth-deploy-dispatch

echo "Auth implantado no commit $commit_sha"

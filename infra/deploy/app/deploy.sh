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
release_dir="$base_dir/app-releases/$commit_sha"
env_file="${APP_ENV_FILE:-/etc/revesbot/app.env}"
lock_file="$base_dir/shared/app-deploy.lock"
previous_target="$(readlink -f "$base_dir/app-current" 2>/dev/null || true)"
npm_cache="/var/cache/npm/revesbot-app"

exec 9>"$lock_file"
flock -n 9 || { echo "Outro deploy do app esta em andamento." >&2; exit 1; }
test -d "$repository/.git"
test -s "$env_file"

set -a
# shellcheck disable=SC1090
source "$env_file"
set +a

: "${MONGO_URL:?MONGO_URL nao configurada}"
: "${JWT_SECRET:?JWT_SECRET nao configurado}"
: "${ENCRYPTION_KEY:?ENCRYPTION_KEY nao configurada}"
: "${EXPRESS_URL:?EXPRESS_URL nao configurada}"
: "${BET_WS_URL:?BET_WS_URL nao configurada}"
: "${BET_WS_TOKEN:?BET_WS_TOKEN nao configurado}"
: "${HOUSE_AGENT_URL:?HOUSE_AGENT_URL nao configurada}"
: "${HOUSE_AGENT_TOKEN:?HOUSE_AGENT_TOKEN nao configurado}"
: "${NEXT_PUBLIC_VIDEO_BASE:?NEXT_PUBLIC_VIDEO_BASE nao configurada}"

sudo -u "$runtime_user" git -C "$repository" fetch --prune origin "$deploy_ref"
if ! sudo -u "$runtime_user" git -C "$repository" cat-file -e "$commit_sha^{commit}" 2>/dev/null; then
  sudo -u "$runtime_user" git -C "$repository" fetch origin "$commit_sha"
fi
sudo -u "$runtime_user" git -C "$repository" cat-file -e "$commit_sha^{commit}"

if [[ ! -d "$release_dir" ]]; then
  sudo -u "$runtime_user" git -C "$repository" worktree add --detach "$release_dir" "$commit_sha"
fi

for app_name in app bet_ws house_agent; do
  app_dir="$release_dir/apps/$app_name"
  test -f "$app_dir/package-lock.json"
  sudo -u "$runtime_user" env PUPPETEER_SKIP_DOWNLOAD=true \
    npm ci --prefix "$app_dir" --cache "$npm_cache"
done

sudo -u "$runtime_user" npm --prefix "$release_dir/apps/bet_ws" test
sudo -u "$runtime_user" npm --prefix "$release_dir/apps/house_agent" test
sudo -u "$runtime_user" --preserve-env npm --prefix "$release_dir/apps/app" run lint
sudo -u "$runtime_user" --preserve-env npm --prefix "$release_dir/apps/app" run build

sudo -u "$runtime_user" --preserve-env node -e \
  "const {MongoClient}=require('$release_dir/apps/app/node_modules/mongodb'); (async()=>{const c=new MongoClient(process.env.MONGO_URL); await c.connect(); await c.db(process.env.MONGO_DB||'roleta_db').command({ping:1}); await c.close(); console.log('database-ok')})().catch(e=>{console.error(e.message);process.exit(1)})"

ln -sfn "$release_dir" "$base_dir/app-current.next"
mv -Tf "$base_dir/app-current.next" "$base_dir/app-current"
chown -h "$runtime_user:$runtime_user" "$base_dir/app-current"

pm2_config="$base_dir/app-current/infra/pm2/app-stack.config.js"
if ! sudo -u "$runtime_user" --preserve-env \
    env PM2_HOME="/home/$runtime_user/.pm2" REVESBOT_APP_CURRENT="$base_dir/app-current" \
    pm2 startOrReload "$pm2_config" --only revesbot-app --update-env; then
  [[ -n "$previous_target" ]] && ln -sfn "$previous_target" "$base_dir/app-current"
  exit 1
fi

if [[ "${DEPLOY_AUX_SERVICES:-0}" == "1" ]]; then
  sudo -u "$runtime_user" --preserve-env \
    env PM2_HOME="/home/$runtime_user/.pm2" REVESBOT_APP_CURRENT="$base_dir/app-current" \
    pm2 startOrReload "$pm2_config" --only revesbot-bet-ws,revesbot-house-agent --update-env
fi

if ! "$base_dir/app-current/infra/deploy/app/healthcheck.sh"; then
  if [[ -n "$previous_target" && -d "$previous_target" ]]; then
    ln -sfn "$previous_target" "$base_dir/app-current"
    sudo -u "$runtime_user" --preserve-env \
      env PM2_HOME="/home/$runtime_user/.pm2" REVESBOT_APP_CURRENT="$base_dir/app-current" \
      pm2 startOrReload "$base_dir/app-current/infra/pm2/app-stack.config.js" --only revesbot-app --update-env
  fi
  echo "Deploy revertido porque o app nao ficou saudavel." >&2
  exit 1
fi

install -m 0644 "$base_dir/app-current/infra/systemd/revesbot-app-health.service" /etc/systemd/system/
install -m 0644 "$base_dir/app-current/infra/systemd/revesbot-app-health.timer" /etc/systemd/system/
install -m 0644 "$base_dir/app-current/infra/logrotate/revesbot-app" /etc/logrotate.d/revesbot-app
systemctl daemon-reload
systemctl enable --now revesbot-app-health.timer

sudo -u "$runtime_user" env PM2_HOME="/home/$runtime_user/.pm2" pm2 save

mapfile -t old_releases < <(find "$base_dir/app-releases" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -nr | tail -n +4 | cut -d' ' -f2-)
for old_release in "${old_releases[@]}"; do
  [[ "$old_release" == "$(readlink -f "$base_dir/app-current")" ]] && continue
  sudo -u "$runtime_user" git -C "$repository" worktree remove --force "$old_release" || true
done

install -m 0755 "$base_dir/app-current/infra/deploy/app/deploy.sh" /usr/local/sbin/revesbot-app-deploy.next
mv -f /usr/local/sbin/revesbot-app-deploy.next /usr/local/sbin/revesbot-app-deploy
install -m 0755 "$base_dir/app-current/infra/deploy/app/ssh-dispatch.sh" /usr/local/sbin/revesbot-app-deploy-dispatch

echo "App implantado no commit $commit_sha"

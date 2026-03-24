#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Run this script as root." >&2
  exit 1
fi

repo_url="${REPO_URL:-https://github.com/allanRoberto/revesbot-final.git}"
base_dir="${BASE_DIR:-/var/www/revesbot-final}"
nginx_source="$base_dir/main/infra/nginx/revesbot.conf"
nginx_target="/etc/nginx/sites-available/revesbot.conf"

echo "==> Installing base packages"
apt-get update
apt-get install -y git curl nginx python3 python3-venv python3-pip build-essential

if ! command -v node >/dev/null 2>&1; then
  echo "==> Installing Node.js 20"
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
fi

if ! command -v pm2 >/dev/null 2>&1; then
  echo "==> Installing PM2"
  npm install -g pm2
fi

mkdir -p "$base_dir" /etc/revesbot
mkdir -p /var/cache/npm/revesbot-auth-api /var/cache/puppeteer

for stage in develop main; do
  target_dir="$base_dir/$stage"
  echo "==> Preparing checkout: $target_dir"

  if [[ ! -d "$target_dir/.git" ]]; then
    git clone "$repo_url" "$target_dir"
  fi

  cd "$target_dir"
  git fetch origin "$stage"

  if git show-ref --verify --quiet "refs/heads/$stage"; then
    git checkout "$stage"
  else
    git checkout -b "$stage" "origin/$stage"
  fi

  git reset --hard "origin/$stage"
done

echo "==> Installing Nginx config"
ln -sf "$nginx_source" "$nginx_target"
ln -sf "$nginx_target" /etc/nginx/sites-enabled/revesbot.conf
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx || systemctl restart nginx

cat <<'EOF'

Bootstrap finished.

Next steps:
1. Create /etc/revesbot/develop.env
2. Create /etc/revesbot/main.env
3. Run:
   /opt/revesbot-final/develop/infra/deploy/deploy.sh develop
   /opt/revesbot-final/main/infra/deploy/deploy.sh main
4. Add the GitHub secret DEPLOY_SSH_KEY with the private key that can SSH into this server.
5. If auth_api uses Puppeteer in runtime, keep /var/cache/puppeteer persisted between deploys.

Expected PM2 processes after first deploy:
- api-dev
- auth-api-dev
- api-prod
- auth-api-prod

EOF

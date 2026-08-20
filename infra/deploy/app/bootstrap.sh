#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Execute como root." >&2
  exit 1
fi

base_dir="${REVESBOT_BASE_DIR:-/var/www/revesbot}"
runtime_user="${REVESBOT_RUNTIME_USER:-revesbot}"
repository="$base_dir/repository"
source_root="${REVESBOT_SOURCE_ROOT:-$repository}"
env_file="/etc/revesbot/app.env"

command -v git >/dev/null
command -v npm >/dev/null
command -v pm2 >/dev/null
command -v nginx >/dev/null
command -v chromium >/dev/null
command -v xvfb-run >/dev/null
test -d "$repository/.git"

if [[ ! -s "$env_file" ]]; then
  test -s /etc/revesbot/app-legacy.env
  bash "$source_root/infra/deploy/app/provision-env.sh"
fi
test -s "$env_file"

install -d -o "$runtime_user" -g "$runtime_user" "$base_dir/app-releases"
install -d -o "$runtime_user" -g "$runtime_user" "$base_dir/shared"
install -d -o "$runtime_user" -g "$runtime_user" /var/cache/npm/revesbot-app

install -m 0755 "$source_root/infra/deploy/app/deploy.sh" /usr/local/sbin/revesbot-app-deploy
install -m 0755 "$source_root/infra/deploy/app/ssh-dispatch.sh" /usr/local/sbin/revesbot-app-deploy-dispatch
install -m 0755 "$source_root/infra/deploy/app/provision-env.sh" /usr/local/sbin/revesbot-app-provision-env
install -m 0644 "$source_root/infra/nginx/app-revesbot.conf" /etc/nginx/sites-available/app-revesbot.conf
ln -sfn /etc/nginx/sites-available/app-revesbot.conf /etc/nginx/sites-enabled/app-revesbot.conf

sudoers_file=/etc/sudoers.d/revesbot-app-deploy
printf '%s ALL=(root) NOPASSWD: /usr/local/sbin/revesbot-app-deploy *\n' "$runtime_user" > "$sudoers_file"
chmod 0440 "$sudoers_file"
visudo -cf "$sudoers_file" >/dev/null

nginx -t
systemctl reload nginx

echo "Bootstrap do app concluido."

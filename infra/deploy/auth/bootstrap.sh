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
env_file="/etc/revesbot/auth.env"

command -v git >/dev/null
command -v npm >/dev/null
command -v pm2 >/dev/null
command -v nginx >/dev/null
test -d "$repository/.git"

install -d -o "$runtime_user" -g "$runtime_user" "$base_dir/auth-releases"
install -d -o "$runtime_user" -g "$runtime_user" "$base_dir/shared"
install -d -o "$runtime_user" -g "$runtime_user" /var/cache/npm/revesbot-auth
install -d -m 0750 -o root -g "$runtime_user" /etc/revesbot

if [[ ! -s "$env_file" ]]; then
  umask 0077
  printf 'AUTH_HOST=127.0.0.1\nAUTH_PORT=3090\nAPP_ORIGINS=https://app.revesbot.com.br\n' > "$env_file"
  chown root:"$runtime_user" "$env_file"
  chmod 0640 "$env_file"
fi

install -m 0755 "$source_root/infra/deploy/auth/deploy.sh" /usr/local/sbin/revesbot-auth-deploy
install -m 0755 "$source_root/infra/deploy/auth/ssh-dispatch.sh" /usr/local/sbin/revesbot-auth-deploy-dispatch
install -m 0644 "$source_root/infra/nginx/auth-revesbot.conf" /etc/nginx/sites-available/auth-revesbot.conf
ln -sfn /etc/nginx/sites-available/auth-revesbot.conf /etc/nginx/sites-enabled/auth-revesbot.conf

sudoers_file=/etc/sudoers.d/revesbot-auth-deploy
printf '%s ALL=(root) NOPASSWD: /usr/local/sbin/revesbot-auth-deploy *\n' "$runtime_user" > "$sudoers_file"
chmod 0440 "$sudoers_file"
visudo -cf "$sudoers_file" >/dev/null

nginx -t
systemctl reload nginx

echo "Bootstrap do auth concluido."

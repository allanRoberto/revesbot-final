#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Execute como root." >&2
  exit 1
fi

repo_url="${REPO_URL:-https://github.com/allanRoberto/revesbot-final.git}"
base_dir="${REVESBOT_BASE_DIR:-/var/www/revesbot}"
runtime_user="${REVESBOT_RUNTIME_USER:-revesbot}"

apt-get update
apt-get install -y git curl logrotate python3 python3-venv python3-pip build-essential

if ! command -v node >/dev/null 2>&1; then
  echo "Node.js deve ser instalado antes do PM2." >&2
  exit 1
fi
if ! command -v pm2 >/dev/null 2>&1; then
  npm install -g pm2
fi
if ! id "$runtime_user" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash "$runtime_user"
fi

install -d -o "$runtime_user" -g "$runtime_user" "$base_dir"
install -d -o "$runtime_user" -g "$runtime_user" \
  "$base_dir/releases" "$base_dir/shared" "$base_dir/shared/state"
install -d -m 0750 -o root -g "$runtime_user" /etc/revesbot

if [[ ! -d "$base_dir/repository/.git" ]]; then
  sudo -u "$runtime_user" git clone "$repo_url" "$base_dir/repository"
fi

env_file=/etc/revesbot/collector.env
if [[ ! -f "$env_file" ]]; then
  install -m 0640 -o root -g "$runtime_user" /dev/null "$env_file"
  echo "Arquivo criado: $env_file. Preencha antes do primeiro deploy." >&2
fi

install -m 0644 "$base_dir/repository/infra/systemd/revesbot-collector-watchdog.service" \
  /etc/systemd/system/revesbot-collector-watchdog.service
install -m 0644 "$base_dir/repository/infra/systemd/revesbot-collector-watchdog.timer" \
  /etc/systemd/system/revesbot-collector-watchdog.timer
install -m 0644 "$base_dir/repository/infra/logrotate/revesbot-collector" \
  /etc/logrotate.d/revesbot-collector
install -m 0755 "$base_dir/repository/infra/deploy/collector/ssh-dispatch.sh" \
  /usr/local/sbin/revesbot-collector-deploy-dispatch

env PATH="/usr/local/bin:/usr/bin:/bin" pm2 startup systemd -u "$runtime_user" --hp "/home/$runtime_user" >/dev/null
systemctl daemon-reload
systemctl enable revesbot-collector-watchdog.timer

echo "Bootstrap concluido em $base_dir"

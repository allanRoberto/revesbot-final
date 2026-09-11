#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Execute via sudo." >&2
  exit 1
fi

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
unset CDPATH ENV BASH_ENV PYTHONHOME PYTHONPATH

commit_sha="${1:-}"
[[ "$commit_sha" =~ ^[0-9a-f]{40}$ ]] || { echo "Informe o SHA Git completo." >&2; exit 1; }

base_dir="/var/www/revesbot"
runtime_user="revesbot"
releases_dir="$base_dir/api-releases"
release_dir="$releases_dir/$commit_sha"
env_file="/etc/revesbot/api.env"
trusted_repository="${REVESBOT_API_TRUSTED_REPOSITORY:-/var/lib/revesbot-api-deploy/repository.git}"
trusted_ref="refs/heads/main"
lock_file="/var/lib/revesbot-api-deploy/deploy.lock"
behavior_process_name="revesbot-behavior-lab"
api_process_name="revesbot-api"
previous_target=""
previous_had_behavior_worker=0
activation_epoch=0
build_dir=""
release_was_built=0
next_link=""

cd /var/lib/revesbot-api-deploy

trusted_git() {
  env -i \
    PATH="$PATH" \
    HOME=/root \
    GIT_CONFIG_NOSYSTEM=1 \
    GIT_CONFIG_GLOBAL=/dev/null \
    GIT_NO_REPLACE_OBJECTS=1 \
    git --git-dir="$trusted_repository" "$@"
}

validate_sealed_release() {
  local candidate="$1"
  local expected_sha="${2:-$commit_sha}"
  RELEASE_CANDIDATE="$candidate" \
  EXPECTED_RELEASE_SHA="$expected_sha" \
  EXPECTED_RELEASES_DIR="$releases_dir" \
    /usr/bin/python3 -I -c '
import os
import pathlib
import stat

candidate = pathlib.Path(os.environ["RELEASE_CANDIDATE"])
releases = pathlib.Path(os.environ["EXPECTED_RELEASES_DIR"]).resolve(strict=True)
resolved = candidate.resolve(strict=True)
if resolved.parent != releases:
    raise SystemExit("release fora do diretorio permitido")
parent_stat = releases.stat()
if parent_stat.st_uid != 0 or parent_stat.st_mode & 0o022:
    raise SystemExit("diretorio de releases nao esta protegido")
base_stat = releases.parent.stat()
if base_stat.st_uid != 0 or base_stat.st_mode & 0o022:
    raise SystemExit("diretorio base nao esta protegido")
marker = resolved / ".release-commit"
if marker.is_symlink() or marker.read_text(encoding="utf-8").strip() != os.environ["EXPECTED_RELEASE_SHA"]:
    raise SystemExit("marcador de release invalido")
for path in (resolved, *resolved.rglob("*")):
    metadata = path.lstat()
    if metadata.st_uid != 0:
        raise SystemExit(f"arquivo fora da propriedade root: {path}")
    if not stat.S_ISLNK(metadata.st_mode) and metadata.st_mode & (stat.S_ISUID | stat.S_ISGID):
        raise SystemExit(f"arquivo privilegiado dentro do release: {path}")
    if not stat.S_ISLNK(metadata.st_mode) and metadata.st_mode & 0o022:
        raise SystemExit(f"arquivo gravavel pelo runtime: {path}")
'
}

validate_root_secret_file() {
  local candidate="$1"
  SECRET_FILE="$candidate" /usr/bin/python3 -I -c '
import os
import pathlib
import stat

path = pathlib.Path(os.environ["SECRET_FILE"])
metadata = path.lstat()
if not stat.S_ISREG(metadata.st_mode):
    raise SystemExit("arquivo de ambiente nao e regular")
if metadata.st_uid != 0 or metadata.st_mode & 0o022:
    raise SystemExit("arquivo de ambiente nao esta protegido")
parent = path.parent.stat()
if parent.st_uid != 0 or parent.st_mode & 0o022:
    raise SystemExit("diretorio do ambiente nao esta protegido")
'
}

cleanup_build() {
  if [[ -n "$build_dir" && -d "$build_dir" ]]; then
    rm -rf -- "$build_dir"
  fi
}

if [[ -L "$base_dir/api-current" ]]; then
  candidate_target="$(readlink -f "$base_dir/api-current" 2>/dev/null || true)"
  if [[ -n "$candidate_target" \
      && -d "$candidate_target" \
      && "$candidate_target" == "$releases_dir/"* ]]; then
    previous_target="$candidate_target"
  fi
fi

pm2_config_has_process() {
  local config_file="$1"
  local process_name="$2"
  local config_root="${config_file%/infra/pm2/api-minimal.config.js}"

  [[ -f "$config_file" ]] || return 1
  sudo -u "$runtime_user" env REVESBOT_API_CURRENT="$config_root" node -e '
    const config = require(process.argv[1]);
    const processName = process.argv[2];
    process.exit(Array.isArray(config.apps) && config.apps.some((app) => app.name === processName) ? 0 : 1);
  ' "$config_file" "$process_name"
}

if [[ -n "$previous_target" ]] \
    && pm2_config_has_process "$previous_target/infra/pm2/api-minimal.config.js" "$behavior_process_name"; then
  previous_had_behavior_worker=1
fi

exec 9>"$lock_file"
flock -n 9 || { echo "Outro deploy da API esta em andamento." >&2; exit 1; }
test -d "$trusted_repository"
test -s "$env_file"
validate_root_secret_file "$env_file"
trusted_head="$(trusted_git rev-parse "$trusted_ref^{commit}")"
trusted_git merge-base --is-ancestor "$commit_sha" "$trusted_head"
[[ "$(trusted_git show "$commit_sha:infra/deploy/api/DRIVER_CONTRACT")" == "revesbot-api-driver-v1" ]]

if [[ "$previous_target" == "$release_dir" ]]; then
  validate_sealed_release "$release_dir"
  if REVESBOT_API_CURRENT="$base_dir/api-current" \
      REVESBOT_RUNTIME_USER="$runtime_user" \
      API_ENV_FILE="$env_file" \
      "$previous_target/infra/deploy/api/healthcheck.sh" >/dev/null; then
    echo "API ja esta saudavel no commit $commit_sha"
    exit 0
  fi

  # Um retry do mesmo SHA pode recuperar processos sem reconstruir o venv que
  # esta em uso nem fingir que o proprio release e uma opcao de rollback.
  set -a
  # shellcheck disable=SC1090
  source "$env_file"
  set +a
  : "${MONGO_URL:?MONGO_URL nao configurada}"
  : "${PIXGO_MONGO_URL:?PIXGO_MONGO_URL nao configurada}"
  : "${REDIS_CONNECT:?REDIS_CONNECT nao configurada}"
  : "${PIXGO_API_KEY:?PIXGO_API_KEY nao configurada}"
  : "${PIXGO_WEBHOOK_SECRET:?PIXGO_WEBHOOK_SECRET nao configurada}"
  sudo -u "$runtime_user" --preserve-env \
    env PM2_HOME="/home/$runtime_user/.pm2" \
    REVESBOT_API_CURRENT="$base_dir/api-current" \
    pm2 startOrReload \
      "$base_dir/api-current/infra/pm2/api-minimal.config.js" \
      --update-env
  if REVESBOT_API_CURRENT="$base_dir/api-current" \
      REVESBOT_RUNTIME_USER="$runtime_user" \
      API_ENV_FILE="$env_file" \
      "$previous_target/infra/deploy/api/healthcheck.sh"; then
    sudo -u "$runtime_user" env PM2_HOME="/home/$runtime_user/.pm2" pm2 save
    echo "API recuperada no commit $commit_sha"
    exit 0
  fi
  echo "O commit $commit_sha ja esta ativo, mas a recuperacao nao ficou saudavel." >&2
  exit 1
fi

if [[ -d "$release_dir" ]]; then
  validate_sealed_release "$release_dir"
  validation_root="$release_dir"
else
  build_dir="$(mktemp -d "$releases_dir/.api-$commit_sha.XXXXXX")"
  chmod 0755 "$build_dir"
  trap cleanup_build EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  trusted_git archive --format=tar "$commit_sha" | tar -xf - -C "$build_dir"
  install -d -m 0755 -o "$runtime_user" -g "$runtime_user" "$build_dir/.venv"
  sudo -u "$runtime_user" env HOME="/home/$runtime_user" \
    /usr/bin/python3 -I -m venv "$build_dir/.venv"
  sudo -u "$runtime_user" env HOME="/home/$runtime_user" \
    "$build_dir/.venv/bin/python" -I -m pip install --disable-pip-version-check \
    -r "$build_dir/apps/api/requirements-minimal.txt" \
    -r "$build_dir/apps/behavior_lab/requirements.txt" \
    pytest
  validation_root="$build_dir"
  release_was_built=1
fi

cd "$validation_root"
sudo -u "$runtime_user" node --check infra/pm2/api-minimal.config.js
sudo -u "$runtime_user" node --check apps/api/static/js/pages/behavior-lab.js
sudo -u "$runtime_user" env REVESBOT_API_CURRENT="$validation_root" \
  node -e 'require("./infra/pm2/api-minimal.config.js")'
sudo -u "$runtime_user" bash -n \
  infra/deploy/api/driver.sh \
  infra/deploy/api/deploy.sh \
  infra/deploy/api/bootstrap.sh \
  infra/deploy/api/healthcheck.sh \
  infra/deploy/api/watchdog.sh
if (( release_was_built == 1 )); then
  sudo -u "$runtime_user" env \
    PYTHONPYCACHEPREFIX="$validation_root/.venv/.validation-pycache" \
    PYTHONPATH="$validation_root:$validation_root/apps" \
    "$validation_root/.venv/bin/python" -m compileall -q \
    apps/behavior_lab \
    apps/api/minimal_main.py \
    apps/api/routes/behavior_lab.py
fi
sudo -u "$runtime_user" env \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH="$validation_root:$validation_root/apps" \
  "$validation_root/.venv/bin/python" -m pytest -q -p no:cacheprovider \
  apps/behavior_lab/tests \
  apps/api/tests/test_behavior_lab_routes.py \
  apps/api/tests/test_roulette_history_route.py \
  apps/api/tests/test_results_websocket.py \
  apps/api/tests/test_minimal_api.py \
  apps/api/tests/test_pattern_monitoring.py \
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
  env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$validation_root/apps" \
  "$validation_root/.venv/bin/python" -c \
  'import asyncio; from api.core.runtime_db import ping_runtime_dependencies; asyncio.run(ping_runtime_dependencies()); print("databases-ok")'

if (( release_was_built == 1 )); then
  printf '%s\n' "$commit_sha" > "$build_dir/.release-commit"
  chown -R -h root:root "$build_dir"
  chmod -R a-s "$build_dir"
  chmod -R go-w "$build_dir"
  validate_sealed_release "$build_dir"
  mv "$build_dir" "$release_dir"
  build_dir=""
  trap - EXIT INT TERM
fi

pm2_api() {
  sudo -u "$runtime_user" --preserve-env \
    env PM2_HOME="/home/$runtime_user/.pm2" \
    REVESBOT_API_CURRENT="$base_dir/api-current" \
    pm2 "$@"
}

reload_api() {
  pm2_api startOrReload \
    "$base_dir/api-current/infra/pm2/api-minimal.config.js" \
    --update-env
}

previous_release_is_healthy() {
  local health_payload=""
  local history_payload=""
  local previous_worker_pid=""
  local expected_previous_release="${previous_target##*/}"

  for ((rollback_attempt = 1; rollback_attempt <= 12; rollback_attempt++)); do
    history_payload="$(
      curl -fsS --max-time 5 -H 'Accept: application/json' \
        'http://127.0.0.1:8082/history/pragmatic-auto-roulette?limit=1' \
        2>/dev/null || true
    )"
    if [[ "$history_payload" == *'"results"'* ]] \
        && [[ "$history_payload" == *'"items"'* ]] \
        && [[ "$(pm2_api pid "$api_process_name" 2>/dev/null | awk 'NF { print $1; exit }')" =~ ^[1-9][0-9]*$ ]]; then
      if (( previous_had_behavior_worker == 0 )); then
        return 0
      fi
      previous_worker_pid="$(
        pm2_api pid "$behavior_process_name" 2>/dev/null \
          | awk 'NF { print $1; exit }' \
          || true
      )"
      if [[ ! "$previous_worker_pid" =~ ^[1-9][0-9]*$ ]]; then
        if (( rollback_attempt < 12 )); then
          sleep 5
        fi
        continue
      fi
      health_payload="$(
        curl -fsS --max-time 5 -H 'Accept: application/json' \
          'http://127.0.0.1:8082/api/patterns/behavior-lab/health' \
          2>/dev/null || true
      )"
      if HEALTH_PAYLOAD="$health_payload" EXPECTED_RELEASE="$expected_previous_release" \
          /usr/bin/python3 -I -c '
import json
import os

payload = json.loads(os.environ["HEALTH_PAYLOAD"])
if payload.get("status") != "healthy":
    raise SystemExit(1)
if payload.get("fresh") is not True or payload.get("ws_connected") is not True:
    raise SystemExit(1)
if payload.get("release_id") != os.environ["EXPECTED_RELEASE"]:
    raise SystemExit(1)
' >/dev/null 2>&1; then
        return 0
      fi
    fi
    if (( rollback_attempt < 12 )); then
      sleep 5
    fi
  done
  return 1
}

rollback_api() {
  local rollback_status=0
  local current_target=""
  local remaining_api_pid="0"
  local remaining_worker_pid="0"
  local rollback_link="$base_dir/.api-current-rollback-$BASHPID"

  if [[ -n "$previous_target" && -d "$previous_target" ]]; then
    if [[ ! -e "$rollback_link" && ! -L "$rollback_link" ]] \
        && ln -s "$previous_target" "$rollback_link" \
        && mv -Tf "$rollback_link" "$base_dir/api-current" \
        && chown -h root:root "$base_dir/api-current"; then
      reload_api || rollback_status=1
    else
      rollback_status=1
    fi
  else
    # Primeira instalacao: nao existe release anterior para restaurar. Remova
    # somente o link exato ativado nesta tentativa e os processos que ela criou,
    # deixando o mesmo SHA apto a uma nova tentativa.
    current_target="$(readlink -f "$base_dir/api-current" 2>/dev/null || true)"
    if [[ -L "$base_dir/api-current" && "$current_target" == "$release_dir" ]]; then
      unlink "$base_dir/api-current" || rollback_status=1
    elif [[ -e "$base_dir/api-current" || -L "$base_dir/api-current" ]]; then
      rollback_status=1
    fi
    pm2_api delete "$api_process_name" >/dev/null 2>&1 || true
    remaining_api_pid="$(
      pm2_api pid "$api_process_name" 2>/dev/null \
        | awk 'NF { print $1; exit }' \
        || true
    )"
    if [[ "$remaining_api_pid" =~ ^[1-9][0-9]*$ ]]; then
      rollback_status=1
    fi
  fi

  if (( previous_had_behavior_worker == 0 )); then
    # startOrReload nao remove processos que desapareceram do arquivo antigo.
    # Sem esta exclusao, um rollback da primeira release do worker o deixaria
    # executando contra um codigo que ja nao esta ativo.
    pm2_api delete "$behavior_process_name" >/dev/null 2>&1 || true
    remaining_worker_pid="$(
      pm2_api pid "$behavior_process_name" 2>/dev/null \
        | awk 'NF { print $1; exit }' \
        || true
    )"
    if [[ "$remaining_worker_pid" =~ ^[1-9][0-9]*$ ]]; then
      rollback_status=1
    fi
  fi

  if [[ -L "$rollback_link" ]] \
      && [[ "$(readlink -f "$rollback_link" 2>/dev/null || true)" == "$previous_target" ]]; then
    unlink "$rollback_link" || rollback_status=1
  fi

  pm2_api save >/dev/null || rollback_status=1
  if [[ -n "$previous_target" ]]; then
    previous_release_is_healthy || rollback_status=1
  fi
  return "$rollback_status"
}

cutover_started=0
deploy_complete=0

rollback_on_exit() {
  local original_status="$1"
  trap - EXIT INT TERM
  if [[ -n "$next_link" && -L "$next_link" ]] \
      && [[ "$(readlink -f "$next_link" 2>/dev/null || true)" == "$release_dir" ]]; then
    unlink "$next_link" || true
  fi
  if (( cutover_started == 1 && deploy_complete == 0 )); then
    if ! rollback_api; then
      echo "O rollback automatico falhou; verifique imediatamente o PM2." >&2
    fi
  fi
  exit "$original_status"
}

trap 'rollback_on_exit "$?"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
next_link="$base_dir/.api-current-$commit_sha-$BASHPID"
[[ ! -e "$next_link" && ! -L "$next_link" ]]
ln -s "$release_dir" "$next_link"
cutover_started=1
mv -Tf "$next_link" "$base_dir/api-current"
chown -h root:root "$base_dir/api-current"
activation_epoch="$(date +%s)"

activate_release() {
  install -m 0755 \
    "$base_dir/api-current/infra/deploy/api/watchdog.sh" \
    /usr/local/sbin/revesbot-api-watchdog.next \
    && mv -f \
      /usr/local/sbin/revesbot-api-watchdog.next \
      /usr/local/sbin/revesbot-api-watchdog \
    && install -m 0644 \
      "$base_dir/api-current/infra/systemd/revesbot-api-watchdog.service" \
      /etc/systemd/system/ \
    && install -m 0644 \
      "$base_dir/api-current/infra/systemd/revesbot-api-watchdog.timer" \
      /etc/systemd/system/ \
    && install -m 0644 \
      "$base_dir/api-current/infra/logrotate/revesbot-api" \
      /etc/logrotate.d/revesbot-api \
    && systemctl daemon-reload \
    && systemctl enable --now revesbot-api-watchdog.timer \
    && reload_api \
    && REVESBOT_API_CURRENT="$base_dir/api-current" \
      REVESBOT_RUNTIME_USER="$runtime_user" \
      API_ENV_FILE="$env_file" \
      BEHAVIOR_LAB_MIN_STARTED_AT_EPOCH="$activation_epoch" \
      "$base_dir/api-current/infra/deploy/api/healthcheck.sh"
}

if ! activate_release; then
  echo "Ativacao falhou; o rollback automatico sera executado." >&2
  exit 1
fi

pm2_api save
deploy_complete=1
trap - EXIT INT TERM

mapfile -t old_releases < <(find "$releases_dir" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -nr | tail -n +4 | cut -d' ' -f2-)
for old_release in "${old_releases[@]}"; do
  [[ "$old_release" == "$(readlink -f "$base_dir/api-current")" ]] && continue
  [[ "$old_release" == "$releases_dir/"* ]] || continue
  old_release_name="${old_release##*/}"
  [[ "$old_release_name" =~ ^[0-9a-f]{40}$ ]] || continue
  if validate_sealed_release "$old_release" "$old_release_name" >/dev/null 2>&1; then
    rm -rf -- "$old_release"
  fi
done

# O driver estavel sempre extrai o deploy.sh do commit solicitado. Ele so e
# atualizado depois de uma ativacao saudavel.
install -m 0755 "$base_dir/api-current/infra/deploy/api/driver.sh" \
  /usr/local/sbin/revesbot-api-deploy.next
mv -f /usr/local/sbin/revesbot-api-deploy.next /usr/local/sbin/revesbot-api-deploy
install -m 0755 "$base_dir/api-current/infra/deploy/api/ssh-dispatch.sh" \
  /usr/local/sbin/revesbot-api-deploy-dispatch

echo "API implantada no commit $commit_sha"

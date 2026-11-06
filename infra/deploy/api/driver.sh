#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Execute via sudo." >&2
  exit 1
fi

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
unset CDPATH ENV BASH_ENV PYTHONHOME PYTHONPATH

request="${1:-}"
trusted_root="/var/lib/revesbot-api-deploy"
driver_lock="$trusted_root/driver.lock"

if [[ "$request" == "restore-vector-experiments-routes" ]]; then
  [[ "$#" -eq 1 ]] || { echo "Comando operacional invalido." >&2; exit 2; }
  test -d "$trusted_root"
  exec 8>"$driver_lock"
  flock -n 8 || { echo "Outro deploy da API esta sendo preparado." >&2; exit 1; }

  experiment_runtime="$(sudo -u revesbot-vector-experiments env \
    PM2_HOME=/var/lib/revesbot-vector-experiments/pm2 \
    pm2 jlist | /usr/bin/python3 -c '
import json, sys
processes = json.load(sys.stdin)
active = [p for p in processes if p.get("name") == "vector-experiments-api"
          and p.get("pm2_env", {}).get("status") == "online"]
if len(active) != 1:
    raise SystemExit("expected_one_online_experimental_api")
print(active[0]["pm2_env"]["pm_cwd"])
')"
  experiment_runtime="$(readlink -f -- "$experiment_runtime")"
  case "$experiment_runtime" in
    /opt/revesbot-vector-experiments/releases/*) ;;
    *) echo "Runtime experimental rejeitado." >&2; exit 1 ;;
  esac
  test -x "$experiment_runtime/.venv-experiments/bin/python"
  test -f "$experiment_runtime/infra/deploy/vector-experiments/publish.py"
  exec "$experiment_runtime/.venv-experiments/bin/python" \
    "$experiment_runtime/infra/deploy/vector-experiments/publish.py" \
    --runtime "$experiment_runtime" \
    --vhost /etc/nginx/sites-available/api-revesbot.conf
fi

commit_sha="$request"
[[ "$commit_sha" =~ ^[0-9a-f]{40}$ ]] || {
  echo "Informe o SHA Git completo." >&2
  exit 2
}

base_dir="/var/www/revesbot"
deploy_ref="main"
repository_url="https://github.com/allanRoberto/revesbot-final.git"
trusted_repository="$trusted_root/repository.git"

install -d -m 0755 -o root -g root "$base_dir"
install -d -m 0700 -o root -g root "$trusted_root"
install -d -m 0755 -o root -g root "$base_dir/api-releases"
cd "$trusted_root"
if [[ ! -d "$trusted_repository" ]]; then
  env -i PATH="$PATH" HOME=/root GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null \
    git init --bare -q "$trusted_repository"
fi
[[ "$(
  env -i PATH="$PATH" HOME=/root GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null \
    git --git-dir="$trusted_repository" rev-parse --is-bare-repository
)" == "true" ]]

trusted_git() {
  env -i \
    PATH="$PATH" \
    HOME=/root \
    GIT_CONFIG_NOSYSTEM=1 \
    GIT_CONFIG_GLOBAL=/dev/null \
    GIT_NO_REPLACE_OBJECTS=1 \
    git --git-dir="$trusted_repository" "$@"
}

exec 8>"$driver_lock"
flock -n 8 || {
  echo "Outro deploy da API esta sendo preparado." >&2
  exit 1
}

trusted_git fetch --force --prune --no-tags \
  "$repository_url" \
  "+refs/heads/$deploy_ref:refs/heads/$deploy_ref"
fetched_sha="$(trusted_git rev-parse "refs/heads/$deploy_ref^{commit}")"
if ! trusted_git merge-base --is-ancestor "$commit_sha" "$fetched_sha"; then
  echo "O commit solicitado nao pertence a origin/$deploy_ref." >&2
  exit 1
fi
contract="$(
  trusted_git show "$commit_sha:infra/deploy/api/DRIVER_CONTRACT" 2>/dev/null || true
)"
if [[ "$contract" != "revesbot-api-driver-v1" ]]; then
  echo "O commit solicitado nao possui o contrato seguro de deploy." >&2
  exit 1
fi

# Workflows de pushes sucessivos podem terminar fora de ordem. Nunca substitua
# um release selado mais novo por um SHA ancestral que terminou os testes depois.
active_target="$(readlink -f "$base_dir/api-current" 2>/dev/null || true)"
active_marker="$active_target/.release-commit"
if [[ "$active_target" == "$base_dir/api-releases/"* \
    && -d "$active_target" \
    && -f "$active_marker" \
    && ! -L "$active_marker" \
    && "$(stat -c '%u' "$active_target")" == "0" \
    && "$(stat -c '%u' "$active_marker")" == "0" ]]; then
  active_sha="$(tr -d '[:space:]' < "$active_marker")"
  if [[ "$active_sha" =~ ^[0-9a-f]{40}$ ]] \
      && trusted_git cat-file -e "$active_sha^{commit}" 2>/dev/null; then
    if [[ "$active_sha" != "$commit_sha" ]] \
        && trusted_git merge-base --is-ancestor "$commit_sha" "$active_sha"; then
      echo "Deploy ignorado: o release ativo ja e descendente de $commit_sha."
      exit 0
    fi
    if ! trusted_git merge-base --is-ancestor "$active_sha" "$commit_sha"; then
      echo "O commit solicitado nao e sucessor do release ativo." >&2
      exit 1
    fi
  fi
fi

driver_tmp="$(mktemp -d /tmp/revesbot-api-deploy.XXXXXX)"
cleanup() {
  rm -rf -- "$driver_tmp"
}
trap cleanup EXIT INT TERM
trap 'exit 130' INT
trap 'exit 143' TERM

target_script="$driver_tmp/deploy.sh"
trusted_git show "$commit_sha:infra/deploy/api/deploy.sh" > "$target_script"
chmod 0700 "$target_script"
bash -n "$target_script"

env -i \
  PATH="$PATH" \
  HOME=/root \
  REVESBOT_API_TRUSTED_REPOSITORY="$trusted_repository" \
  "$target_script" "$commit_sha"

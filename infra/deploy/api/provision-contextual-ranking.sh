#!/usr/bin/env bash
# Configura uma vez o acesso do contextual-ranking-worker (idempotente).
#
# - Papel MongoDB "contextualRankingWriter": find, insert, update, createIndex e
#   listIndexes somente em roleta_db.contextual_ranking_signals_v1.
# - Usuario revesbot_api_contextual_prod com esse papel; a credencial da API
#   (revesbot_api_prod) continua somente leitura.
# - Grava CONTEXTUAL_RANKING_MONGO_URL e VECTOR_API_TOKEN em /etc/revesbot/api.env.
# - Recarrega apenas o contextual-ranking-worker com o ambiente novo.
#
# Uso: sudo bash provision-contextual-ranking.sh [/etc/revesbot-vector/staging.env]
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Execute como root." >&2
  exit 1
fi

base_dir="${REVESBOT_BASE_DIR:-/var/www/revesbot}"
runtime_user="${REVESBOT_RUNTIME_USER:-revesbot}"
api_env=/etc/revesbot/api.env
mongo_data_env=/etc/revesbot/collector-data-prod.env
vector_env="${1:-/etc/revesbot-vector/staging.env}"
database=roleta_db
collection=contextual_ranking_signals_v1
role_name=contextualRankingWriter
writer_user=revesbot_api_contextual_prod
process_name=contextual-ranking-worker

test -s "$api_env"
test -s "$mongo_data_env"
command -v docker >/dev/null
command -v openssl >/dev/null

env_value() {
  awk -F= -v name="$2" '$1 == name { sub(/^[^=]*=/, ""); print; exit }' "$1"
}

strip_quotes() {
  local value="$1"
  value="${value%\"}"; value="${value#\"}"
  value="${value%\'}"; value="${value#\'}"
  printf '%s' "$value"
}

set_env_value() {
  local name="$1" value="$2" next_file
  next_file="$(mktemp /etc/revesbot/api.env.XXXXXX)"
  awk -v name="$name" -v value="$value" '
    BEGIN { replaced = 0 }
    index($0, name "=") == 1 { print name "=" value; replaced = 1; next }
    { print }
    END { if (!replaced) print name "=" value }
  ' "$api_env" > "$next_file"
  chown root:"$runtime_user" "$next_file"
  chmod 0640 "$next_file"
  mv "$next_file" "$api_env"
}

set -a
# shellcheck disable=SC1090
source "$mongo_data_env"
set +a
: "${MONGO_INITDB_ROOT_USERNAME:?MONGO_INITDB_ROOT_USERNAME ausente em $mongo_data_env}"
: "${MONGO_INITDB_ROOT_PASSWORD:?MONGO_INITDB_ROOT_PASSWORD ausente em $mongo_data_env}"

if [[ -z "$(env_value "$api_env" CONTEXTUAL_RANKING_MONGO_URL)" ]]; then
  writer_password="$(openssl rand -hex 24)"
  docker exec revesbot-mongo-prod mongosh --quiet \
    --username "$MONGO_INITDB_ROOT_USERNAME" \
    --password "$MONGO_INITDB_ROOT_PASSWORD" \
    --authenticationDatabase admin \
    --eval "
      const target = db.getSiblingDB('$database');
      const privileges = [{
        resource: { db: '$database', collection: '$collection' },
        actions: ['find', 'insert', 'update', 'createIndex', 'listIndexes'],
      }];
      if (target.getRole('$role_name')) {
        target.updateRole('$role_name', { privileges: privileges, roles: [] });
      } else {
        target.createRole({ role: '$role_name', privileges: privileges, roles: [] });
      }
      const roles = [{ role: '$role_name', db: '$database' }];
      if (target.getUser('$writer_user')) {
        target.updateUser('$writer_user', { pwd: '$writer_password', roles: roles });
      } else {
        target.createUser({ user: '$writer_user', pwd: '$writer_password', roles: roles });
      }
    " >/dev/null
  set_env_value CONTEXTUAL_RANKING_MONGO_URL \
    "mongodb://$writer_user:$writer_password@127.0.0.1:27018/$database?authSource=$database"
  echo "Usuario $writer_user criado com escrita apenas em $database.$collection."
else
  echo "CONTEXTUAL_RANKING_MONGO_URL ja configurada; usuario mantido."
fi

if [[ -z "$(env_value "$api_env" VECTOR_API_TOKEN)" ]]; then
  if [[ -s "$vector_env" ]]; then
    token="$(strip_quotes "$(env_value "$vector_env" VECTOR_API_TOKEN)")"
    if [[ -n "$token" ]]; then
      set_env_value VECTOR_API_TOKEN "$token"
      echo "VECTOR_API_TOKEN copiado de $vector_env."
    else
      echo "VECTOR_API_TOKEN ausente em $vector_env; configure-o em $api_env." >&2
    fi
  else
    echo "Arquivo $vector_env nao encontrado; informe o caminho como argumento." >&2
  fi
else
  echo "VECTOR_API_TOKEN ja configurado."
fi

pm2_config="$base_dir/api-current/infra/pm2/api-minimal.config.js"
if [[ -f "$pm2_config" ]] && grep -q "\"$process_name\"" "$pm2_config"; then
  set -a
  # shellcheck disable=SC1090
  source "$api_env"
  set +a
  sudo -u "$runtime_user" --preserve-env \
    env PM2_HOME="/home/$runtime_user/.pm2" REVESBOT_API_CURRENT="$base_dir/api-current" \
    pm2 startOrReload "$pm2_config" --only "$process_name" --update-env
  sudo -u "$runtime_user" env PM2_HOME="/home/$runtime_user/.pm2" pm2 save >/dev/null
  echo "$process_name recarregado com o ambiente atualizado."
else
  echo "O release ativo ainda nao tem o $process_name; o proximo deploy o inicia com este ambiente."
fi

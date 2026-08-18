#!/usr/bin/env bash
set -euo pipefail

phase="${1:-}"
archive="${2:-}"
boundary="${3:-}"
database="${MIGRATION_DATABASE:-roleta_db}"
collection="${MIGRATION_COLLECTION:-history}"
container="${MIGRATION_TARGET_CONTAINER:-revesbot-mongo-prod}"
allowed_root="${MIGRATION_ARCHIVE_ROOT:-/var/tmp/revesbot-history-migration}"

usage() {
  echo "Uso: $0 source-full|source-delta|target-full|target-delta ARQUIVO [OBJECT_ID]" >&2
  exit 2
}

[[ -n "$phase" && -n "$archive" ]] || usage
[[ "$archive" == "$allowed_root/"* ]] || {
  echo "Arquivo deve estar dentro de $allowed_root." >&2
  exit 2
}

case "$phase" in
  source-full)
    test -n "${MONGO_URL:-}"
    command -v mongodump >/dev/null
    install -d -m 0700 "$allowed_root"
    test ! -e "$archive"
    boundary_file="$archive.boundary"
    test ! -e "$boundary_file"
    max_id="$(mongosh "$MONGO_URL" --quiet --eval \
      "const d=db.getSiblingDB('$database').getCollection('$collection').find({}, {_id:1}).sort({_id:-1}).limit(1).next(); print(d ? d._id.valueOf() : '')")"
    [[ "$max_id" =~ ^[0-9a-f]{24}$ ]] || {
      echo "Nao foi possivel determinar o ObjectId limite." >&2
      exit 1
    }
    printf '%s\n' "$max_id" > "$boundary_file"
    chmod 0600 "$boundary_file"
    mongodump --uri="$MONGO_URL" --db="$database" --collection="$collection" \
      --archive="$archive" --gzip
    sha256sum "$archive" > "$archive.sha256"
    printf 'boundary=%s\n' "$max_id"
    ;;
  source-delta)
    test -n "${MONGO_URL:-}"
    command -v mongodump >/dev/null
    [[ "$boundary" =~ ^[0-9a-f]{24}$ ]] || usage
    install -d -m 0700 "$allowed_root"
    test ! -e "$archive"
    query_file="$(mktemp "$allowed_root/history-query.XXXXXX.json")"
    trap 'rm -f "$query_file"' EXIT
    printf '{"_id":{"$gt":{"$oid":"%s"}}}\n' "$boundary" > "$query_file"
    mongodump --uri="$MONGO_URL" --db="$database" --collection="$collection" \
      --queryFile="$query_file" --archive="$archive" --gzip
    sha256sum "$archive" > "$archive.sha256"
    ;;
  target-full|target-delta)
    [[ "${EUID:-$(id -u)}" -eq 0 ]] || {
      echo "Restore deve ser executado como root." >&2
      exit 1
    }
    test -s "$archive"
    test -s "$archive.sha256"
    sha256sum --check "$archive.sha256"
    test -s /etc/revesbot/collector-data-prod.env
    set -a
    # shellcheck disable=SC1091
    source /etc/revesbot/collector-data-prod.env
    set +a
    docker inspect "$container" >/dev/null
    container_archive="/tmp/$(basename "$archive")"
    docker cp "$archive" "$container:$container_archive"
    restore_args=(
      mongorestore
      --username "$MONGO_INITDB_ROOT_USERNAME"
      --password "$MONGO_INITDB_ROOT_PASSWORD"
      --authenticationDatabase admin
      --archive="$container_archive"
      --gzip
      --nsInclude "$database.$collection"
    )
    if [[ "$phase" == target-full ]]; then
      [[ "${MIGRATION_ALLOW_DROP:-}" == "$database.$collection" ]] || {
        echo "Defina MIGRATION_ALLOW_DROP=$database.$collection para a carga inicial." >&2
        exit 1
      }
      restore_args+=(--drop)
    else
      restore_args+=(--mode=upsert)
    fi
    docker exec "$container" "${restore_args[@]}"
    docker exec "$container" rm -f "$container_archive"
    ;;
  *)
    usage
    ;;
esac

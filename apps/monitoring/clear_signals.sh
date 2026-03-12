#!/usr/bin/env bash

MODE="${1:-hard}"
if [ "$MODE" != "signals" ] && [ "$MODE" != "hard" ]; then
    echo "Uso: $0 [signals|hard]"
    echo "  signals: limpa apenas keys canônicas de sinais"
    echo "  hard: limpa sinais + streams + consumer groups (padrão)"
    exit 1
fi

warn() {
    echo "[WARN] $1"
}

resolve_redis_mode() {
    if [ -n "${REDIS_CONNECT:-}" ]; then
        REDIS_MODE="url_env"
        warn "modo de conexão: REDIS_CONNECT (env)"
        return
    fi

    if [ -n "${REDIS_HOST:-}" ] || [ -n "${REDIS_PORT:-}" ] || [ -n "${REDIS_PASSWORD:-}" ]; then
        REDIS_MODE="host_port_env"
        REDIS_HOST="${REDIS_HOST:-localhost}"
        REDIS_PORT="${REDIS_PORT:-6379}"
        warn "REDIS_CONNECT ausente; modo de conexão: REDIS_HOST/REDIS_PORT/REDIS_PASSWORD (env)"
        return
    fi

    REDIS_MODE="hardcoded_fallback"
    warn "REDIS_CONNECT e REDIS_HOST/REDIS_PORT/REDIS_PASSWORD ausentes; usando fallback hardcoded final (deprecated)"
    echo "Escolha o ambiente:"
    echo "1) Local (localhost)"
    echo "2) Servidor (remoto)"
    read -r -p "Opção: " option

    case $option in
        1)
            REDIS_HOST="localhost"
            REDIS_PORT="6379"
            REDIS_PASSWORD=""
            ;;
        2)
            REDIS_HOST="45.179.88.134"
            REDIS_PORT="6379"
            REDIS_PASSWORD="09T6iVOEmt7p0lEEXiRZATotvS70fPzK"
            ;;
        *)
            echo "Opção inválida"
            exit 1
            ;;
    esac
}

redis_cmd() {
    if [ "$REDIS_MODE" = "url_env" ]; then
        redis-cli -u "$REDIS_CONNECT" "$@"
        return
    fi

    if [ -n "${REDIS_PASSWORD:-}" ]; then
        redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -a "$REDIS_PASSWORD" "$@"
    else
        redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" "$@"
    fi
}

resolve_redis_mode
echo "Limpando Redis (modo: $REDIS_MODE)..."

cleanup_signals() {
    redis_cmd DEL signals:active >/dev/null
    redis_cmd DEL signals:index:triggers >/dev/null
    redis_cmd --scan --pattern "signal:*" | while IFS= read -r key; do
        [ -n "$key" ] && redis_cmd DEL "$key" >/dev/null
    done
}

cleanup_hard() {
    cleanup_signals
    redis_cmd DEL streams:signals:new >/dev/null
    redis_cmd DEL streams:signals:updates >/dev/null
    redis_cmd XGROUP DESTROY streams:signals:new signal_processors >/dev/null 2>/dev/null || true
    redis_cmd XGROUP DESTROY streams:signals:updates signal_processors >/dev/null 2>/dev/null || true
}

if [ "$MODE" = "signals" ]; then
    echo "Modo: cleanup canônico de sinais"
    cleanup_signals
else
    echo "Modo: hard reset (sinais + streams + groups)"
    cleanup_hard
fi

echo "Limpeza concluída!"

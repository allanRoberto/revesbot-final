import json
import time
import uuid
from typing import Any
from helpers.utils.redis_client import r


SIGNALS_STREAM_KEY = "streams:signals:new"
SIGNALS_ACTIVE_HASH = "signals:active"
SIGNALS_TRIGGERS_INDEX_HASH = "signals:index:triggers"

# Status que DEVEM bloquear duplicado (se existir sinal ativo com mesmos triggers nesses status, ignorar)
DEDUP_BLOCK_STATUSES = {"processing", "waiting", "active"}


def _normalize_int_list(value: int | list[int]) -> list[int]:
    if isinstance(value, list):
        return [int(v) for v in value]
    return [int(value)]


def _triggers_signature(roulette_id: str, pattern: str, triggers: list[int]) -> str:
    # Assinatura determinística: mesma roleta + mesmo padrão + mesmos triggers (ordem não importa)
    normalized = sorted(set(int(t) for t in triggers))
    return f"{roulette_id}:{pattern}:{','.join(map(str, normalized))}"


def _decode_redis_value(value):
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="ignore")
    return value


def _get_active_signal_payload(signal_id: str) -> str | None:
    payload = r.hget(SIGNALS_ACTIVE_HASH, signal_id)
    payload = _decode_redis_value(payload)
    return payload


def _get_existing_signal_id_by_triggers(signature: str) -> str | None:
    existing_id = r.hget(SIGNALS_TRIGGERS_INDEX_HASH, signature)
    existing_id = _decode_redis_value(existing_id)
    if not existing_id:
        return None

    payload = _get_active_signal_payload(existing_id)
    if not payload:
        # Índice apontando pra um sinal que não está mais ativo (ou expirou / foi removido)
        r.hdel(SIGNALS_TRIGGERS_INDEX_HASH, signature)
        return None

    try:
        data = json.loads(payload)
    except Exception:
        # Payload corrompido: não bloqueia novo sinal, e limpa índice
        r.hdel(SIGNALS_TRIGGERS_INDEX_HASH, signature)
        return None

    status = str(data.get("status", "")).lower().strip()

    # Se o sinal existente ainda está "em andamento" (processing/waiting), ignora duplicado
    if status in DEDUP_BLOCK_STATUSES:
        return existing_id

    # Qualquer outro status: libera criar novo (não remove sinal antigo, só não bloqueia por índice)
    r.hdel(SIGNALS_TRIGGERS_INDEX_HASH, signature)
    return None


def save_signal(
    roulette_id: str,
    roulette_name: str,
    roulette_url: str,
    triggers: int | list[int],
    targets: int | list[int],
    bets: int | list[int],
    snapshot: list[int],
    status: str,
    pattern: str,
    passed_spins: int,
    spins_required: int,
    gales: int,
    score: int,
    message: str,
    temp_state,
    create_at,
    timestamp,
    tags: list[str] = None
):
    # Normaliza triggers/targets/bets para sempre serem listas
    triggers = _normalize_int_list(triggers)
    targets = _normalize_int_list(targets)
    bets = _normalize_int_list(bets)

    # Dedupe: se já existe um sinal ativo com os mesmos triggers (na mesma roleta + padrão)
    # e ele estiver em status processing/waiting, ignora
    signature = _triggers_signature(roulette_id=roulette_id, pattern=pattern, triggers=triggers)
    existing_signal_id = _get_existing_signal_id_by_triggers(signature)
    """if existing_signal_id:
        print(
            f"⏭️  Ignorado: já existe sinal ativo com os mesmos triggers "
            f"em status processing/waiting (signal_id={existing_signal_id})"
        )
        return existing_signal_id"""

    signal_id = str(uuid.uuid4())

    new_signal = {
        "id": signal_id,
        "roulette_id": roulette_id,
        "roulette_name": roulette_name,
        "roulette_url": roulette_url,
        "pattern": pattern,
        "triggers": triggers,
        "targets": targets,
        "bets": bets,
        "status": status,
        "history": snapshot[:500],
        "snapshot": snapshot,
        "passed_spins": passed_spins,
        "gales": gales,
        "score": score,
        "spins_after_win": 0,
        "spins_after_cancelled": 0,
        "spins_after_lost": 0,
        "spins_after_trigger": 0,
        "greens_after_wins" : 0,
        "spins_required": spins_required,
        "wait_spins_after_trigger": 0,
        "broadcasted": False,
        "message": message,
        "attempts": 0,
        "tags": tags or [],
        "imediate": False,
        "numbers_after_trigger": [],
        "log": [],
        "created_at": create_at,
        "updated_at": int(time.time()),
        "timestamp": timestamp,
        "type": "new_signal",
        "temp_state" : temp_state
    }

    payload = json.dumps(new_signal, default=str, ensure_ascii=False)

    # 1) Salva no hash para consulta rápida
    key = f"signal:{signal_id}"
    r.lpush(key, payload)
    r.ltrim(key, 0, 0)

    # 2) Adiciona ao Redis Stream
    r.xadd(
        SIGNALS_STREAM_KEY,
        {
            "signal_id": signal_id,
            "data": payload
        },
        maxlen=10000
    )

    # 3) Índice de sinais ativos
    r.hset(
        SIGNALS_ACTIVE_HASH,
        signal_id,
        payload
    )

    # 4) Índice por triggers (dedupe rápido)
    r.hset(SIGNALS_TRIGGERS_INDEX_HASH, signature, signal_id)

    print(f"✅ Sinal {signal_id} salvo e adicionado ao stream")
    return signal_id
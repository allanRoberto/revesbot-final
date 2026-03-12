from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from api.core.redis_client import get_signals_redis_client


router = APIRouter()
signals_redis = get_signals_redis_client()


@router.delete("/signals")
async def reset_signals():
    keys = await signals_redis.keys("signal:*")
    for fixed_key in ("signals:active", "signals:index:triggers"):
        if await signals_redis.exists(fixed_key):
            keys.append(fixed_key)
    if not keys:
        return {"deleted": 0}

    deleted = await signals_redis.delete(*keys)
    return {"deleted": deleted}


@router.get("/signals")
async def list_signals():
    signals = []
    try:
        keys = await signals_redis.keys("signal:*")
        for key in keys:
            key_type = await signals_redis.type(key)
            if key_type != "list":
                continue

            raw_list = await signals_redis.lrange(key, 0, -1)
            for raw in raw_list:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                for field in ("triggers", "targets", "bets"):
                    val = data.get(field)
                    if val is None:
                        data[field] = []
                    elif not isinstance(val, list):
                        data[field] = [val]

                data["wait_spins_after_trigger"] = data.get("wait_spins", 0)
                data.pop("wait_spins", None)

                signals.append(data)

        return signals

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

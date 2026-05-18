from __future__ import annotations

import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.core.db import app_settings_coll, gatilhos_coll, roulettes_config_coll, sinais_coll

router = APIRouter()

_SETTINGS_DEFAULTS: Dict[str, Any] = {
    "gatilho_min_pct": 4.5,
    "auto_exclude_enabled": False,
    "auto_exclude_min_pct": 70.0,
    "auto_exclude_min_sinais": 5,
    "auto_exclude_hot_zone_only": False,
}


class SettingsUpdate(BaseModel):
    gatilho_min_pct: Optional[float] = None
    auto_exclude_enabled: Optional[bool] = None
    auto_exclude_min_pct: Optional[float] = None
    auto_exclude_min_sinais: Optional[int] = None
    auto_exclude_hot_zone_only: Optional[bool] = None


class RouletteUpdate(BaseModel):
    monitor_gatilhos: bool
    activate_sinais: bool


@router.get("/api/config/settings")
async def get_settings() -> Dict[str, Any]:
    doc = await app_settings_coll.find_one({"_id": "global"}) or {}
    return {
        "gatilho_min_pct":            float(doc.get("gatilho_min_pct",            _SETTINGS_DEFAULTS["gatilho_min_pct"])),
        "auto_exclude_enabled":       bool( doc.get("auto_exclude_enabled",       _SETTINGS_DEFAULTS["auto_exclude_enabled"])),
        "auto_exclude_min_pct":       float(doc.get("auto_exclude_min_pct",       _SETTINGS_DEFAULTS["auto_exclude_min_pct"])),
        "auto_exclude_min_sinais":    int(  doc.get("auto_exclude_min_sinais",    _SETTINGS_DEFAULTS["auto_exclude_min_sinais"])),
        "auto_exclude_hot_zone_only": bool( doc.get("auto_exclude_hot_zone_only", _SETTINGS_DEFAULTS["auto_exclude_hot_zone_only"])),
    }


@router.put("/api/config/settings")
async def update_settings(body: SettingsUpdate) -> Dict[str, Any]:
    patch: Dict[str, Any] = {}
    if body.gatilho_min_pct is not None:
        if body.gatilho_min_pct < 1.0 or body.gatilho_min_pct > 30.0:
            raise HTTPException(status_code=400, detail="gatilho_min_pct deve estar entre 1 e 30")
        patch["gatilho_min_pct"] = body.gatilho_min_pct
    if body.auto_exclude_enabled is not None:
        patch["auto_exclude_enabled"] = body.auto_exclude_enabled
    if body.auto_exclude_min_pct is not None:
        if body.auto_exclude_min_pct < 0 or body.auto_exclude_min_pct > 100:
            raise HTTPException(status_code=400, detail="auto_exclude_min_pct deve estar entre 0 e 100")
        patch["auto_exclude_min_pct"] = body.auto_exclude_min_pct
    if body.auto_exclude_min_sinais is not None:
        if body.auto_exclude_min_sinais < 1:
            raise HTTPException(status_code=400, detail="auto_exclude_min_sinais deve ser >= 1")
        patch["auto_exclude_min_sinais"] = body.auto_exclude_min_sinais
    if body.auto_exclude_hot_zone_only is not None:
        patch["auto_exclude_hot_zone_only"] = body.auto_exclude_hot_zone_only
    if not patch:
        raise HTTPException(status_code=400, detail="Nenhum campo fornecido")
    patch["updated_at"] = datetime.datetime.utcnow()
    await app_settings_coll.update_one({"_id": "global"}, {"$set": patch}, upsert=True)
    return patch


@router.get("/api/config/roulettes")
async def get_roulettes() -> Dict[str, Any]:
    docs = await roulettes_config_coll.find({}).sort("name", 1).to_list(length=100)
    return {
        "roulettes": [
            {
                "slug": d["_id"],
                "name": d.get("name", d["_id"]),
                "url": d.get("url", ""),
                "monitor_gatilhos": bool(d.get("monitor_gatilhos", False)),
                "activate_sinais": bool(d.get("activate_sinais", False)),
            }
            for d in docs
        ]
    }


@router.put("/api/config/roulettes/{slug}")
async def update_roulette(slug: str, body: RouletteUpdate) -> Dict[str, Any]:
    result = await roulettes_config_coll.update_one(
        {"_id": slug},
        {"$set": {
            "monitor_gatilhos": body.monitor_gatilhos,
            "activate_sinais": body.activate_sinais,
            "updated_at": datetime.datetime.utcnow(),
        }},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Roleta não encontrada")
    return {"slug": slug, "monitor_gatilhos": body.monitor_gatilhos, "activate_sinais": body.activate_sinais}


@router.delete("/api/config/reset")
async def reset_data(target: str = Query(..., description="sinais | gatilhos | all")) -> Dict[str, Any]:
    if target == "sinais":
        r = await sinais_coll.delete_many({})
        await gatilhos_coll.update_many(
            {},
            {"$set": {"signals_won": 0, "signals_lost": 0, "signal_ids": [], "signal_count": 0}},
        )
        return {"deleted_sinais": r.deleted_count, "deleted_gatilhos": 0}
    elif target == "gatilhos":
        rs = await sinais_coll.delete_many({})
        rg = await gatilhos_coll.delete_many({})
        return {"deleted_sinais": rs.deleted_count, "deleted_gatilhos": rg.deleted_count}
    elif target == "all":
        rs = await sinais_coll.delete_many({})
        rg = await gatilhos_coll.delete_many({})
        return {"deleted_sinais": rs.deleted_count, "deleted_gatilhos": rg.deleted_count}
    else:
        raise HTTPException(status_code=400, detail="target inválido: use sinais, gatilhos ou all")

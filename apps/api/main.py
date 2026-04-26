
import os
import pytz
import json
import logging
import certifi
import time



import json
import logging
import asyncio
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect
from redis.exceptions import ResponseError

import zipfile
import io
from typing import Dict, Any, Optional
from fastapi.responses import StreamingResponse, Response

from api.helpers.utils.filters import get_mirror, get_neighbords

from datetime import datetime, timedelta, date

from typing import List, Any, Dict, List, Tuple, Optional, Set
from dotenv import load_dotenv

import math
import pytz

load_dotenv()

logging.basicConfig(
    level=logging.ERROR,  # Você pode mudar para DEBUG ou ERROR se quiser
    format="%(asctime)s - %(levelname)s - %(message)s"
)

from motor.motor_asyncio import AsyncIOMotorClient

from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI, WebSocket, Request, HTTPException, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import  JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from api.core.db import (
    mongo_db,
    history_coll,
    ensure_occurrence_analysis_indexes,
    ensure_suggestion_monitor_indexes,
)
from fastapi.responses import HTMLResponse

from api.helpers.roulettes_list import roulettes

roulette_lookup = {r['slug']: r for r in roulettes}
pragmatic_roulette_slugs = [r["slug"] for r in roulettes if str(r.get("slug", "")).startswith("pragmatic")]
roulette_lookup_by_name = {str(r.get("name", "")): dict(r) for r in roulettes}
_roulettes_cache: Dict[str, Any] = {"expires_at": 0.0, "items": None}
_ROULETTES_CACHE_TTL_SECONDS = 60.0

import asyncio

from api.routes.analysis import router as analysis_router
from api.routes.analysis_sequences import router as analysis_sequences_router
from api.routes.analysis_overview import router as analysis_overview_router
from api.routes.roulette_history import router as roulette_history_router
from api.routes.websocket_signals import router as websocket_signals_router
from api.routes.signals import router as signals_router
from api.routes.pages import router as pages_router
from api.routes.agent import router as agent_router
from api.routes.patterns import router as patterns_router
from api.routes.assertiveness_replay import router as assertiveness_replay_router
from api.routes.decoder_lab import router as decoder_lab_router
from api.routes.ai_shadow import router as ai_shadow_router
from api.routes.monitor_replay import router as monitor_replay_router
from api.routes.occurrence_ranking import router as occurrence_ranking_router
from api.routes.suggestion_monitor import router as suggestion_monitor_router



# Guarde a task globalmente
listener_task = None


def get_roulette_flag(name_or_slug: str) -> str:
    text = str(name_or_slug or "").lower()
    if "brazil" in text or "brazilian" in text:
        return "🇧🇷"
    if "korean" in text:
        return "🇰🇷"
    if "turkish" in text:
        return "🇹🇷"
    if "italian" in text or "italia" in text:
        return "🇮🇹"
    if "romanian" in text:
        return "🇷🇴"
    if "german" in text:
        return "🇩🇪"
    if "russian" in text:
        return "🇷🇺"
    if "vietnamese" in text:
        return "🇻🇳"
    if "macao" in text:
        return "🇲🇴"
    return "🎯"


def get_display_name(name_or_slug: str) -> str:
    raw = str(name_or_slug or "").strip()
    if not raw:
        return "-"
    if raw in roulette_lookup_by_name:
        return str(roulette_lookup_by_name[raw].get("name") or raw)
    lookup = roulette_lookup.get(raw)
    if lookup:
        return str(lookup.get("name") or raw)
    return raw.replace("-", " ").title()

# Função para formatar timestamps para horário de Brasília
def format_timestamp_br(timestamp: int) -> str:
    tz = pytz.timezone("America/Sao_Paulo")
    dt = datetime.fromtimestamp(timestamp, tz)
    return dt.strftime("%d/%m/%Y %H:%M:%S")

app = FastAPI()


@app.middleware("http")
async def log_slow_http_requests(request: Request, call_next):
    started_at = time.perf_counter()
    pid = os.getpid()
    try:
        response = await call_next(request)
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        logging.error(
            "API request failed | pid=%s | method=%s | path=%s | elapsed_ms=%.2f | error=%s",
            pid,
            request.method,
            request.url.path,
            elapsed_ms,
            exc,
        )
        raise

    elapsed_ms = (time.perf_counter() - started_at) * 1000.0
    if elapsed_ms >= 2000.0:
        logging.error(
            "API request slow | pid=%s | method=%s | path=%s | status=%s | elapsed_ms=%.2f | query=%s",
            pid,
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            str(request.url.query or "").strip(),
        )
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analysis_router)
app.include_router(analysis_sequences_router)
app.include_router(analysis_overview_router)
app.include_router(roulette_history_router)
app.include_router(websocket_signals_router)
app.include_router(signals_router)
app.include_router(pages_router)
app.include_router(agent_router)
app.include_router(patterns_router)
app.include_router(assertiveness_replay_router)
app.include_router(decoder_lab_router)
app.include_router(ai_shadow_router)
app.include_router(monitor_replay_router)
app.include_router(occurrence_ranking_router)
app.include_router(suggestion_monitor_router)

 

base_dir = os.path.dirname(__file__)
app.mount("/static", StaticFiles(directory=os.path.join(base_dir, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(base_dir, "templates"))


async def _warm_api_runtime() -> None:
    try:
        await mongo_db.command("ping")
    except Exception as exc:
        logging.error(f"Warmup Mongo ping falhou: {exc}")
    try:
        await ensure_suggestion_monitor_indexes()
    except Exception as exc:
        logging.error(f"Warmup de índices do monitor falhou: {exc}")
    try:
        await ensure_occurrence_analysis_indexes()
    except Exception as exc:
        logging.error(f"Warmup de índices da análise de ocorrências falhou: {exc}")
    try:
        await get_roulettes_list()
    except Exception as exc:
        logging.error(f"Warmup de cache de roletas falhou: {exc}")


@app.on_event("startup")
async def schedule_api_warmup() -> None:
    asyncio.create_task(_warm_api_runtime())


async def get_mongo_history(slug: str, limit: int = 10000) -> List[int]:
    """
    Busca os últimos 'limit' resultados de 'history' para a roleta 'slug',
    ordenados do mais antigo ao mais novo.
    """
    try:
        cursor = (
            history_coll
            .find({"roulette_id": slug})
            .sort("timestamp", 1)
        )

        
        docs = await cursor.to_list()

       # docs.reverse()
        return [doc["value"] for doc in docs]
    except Exception as e:
        print(e)
        logging.error(f"Erro ao buscar histórico no MongoDB: {e}")
        return []

# Adicione esta nova rota no main.py, APÓS a rota /history/{slug} existente

# Adicione essas importações no topo do arquivo main.py (junto com as outras)
import zipfile
import io
from typing import Dict, Any
from fastapi.responses import StreamingResponse, Response

# Adicione essas rotas no seu main.py (antes do final do arquivo)

@app.get("/api/roulettes")
async def get_roulettes_list():
    """
    Retorna lista de todas as roletas Pragmatic com contagem de números
    """
    try:
        now = time.monotonic()
        cached_items = _roulettes_cache.get("items")
        if isinstance(cached_items, list) and float(_roulettes_cache.get("expires_at") or 0.0) > now:
            return cached_items

        pipeline = [
            {"$match": {"roulette_id": {"$in": pragmatic_roulette_slugs}}},
            {"$group": {"_id": "$roulette_id", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ]

        rows = await history_coll.aggregate(pipeline, allowDiskUse=True).to_list(length=None)
        count_by_slug = {
            str(row.get("_id") or "").strip(): int(row.get("count") or 0)
            for row in rows
            if str(row.get("_id") or "").strip()
        }

        enriched_roulettes = []
        for roulette in roulettes:
            slug = str(roulette.get("slug") or "").strip()
            if slug not in pragmatic_roulette_slugs:
                continue
            display_name = str(roulette.get("name") or slug)
            enriched_roulettes.append({
                "slug": slug,
                "name": display_name,
                "count": count_by_slug.get(slug, 0),
                "flag": get_roulette_flag(display_name or slug),
                "displayName": get_display_name(display_name or slug),
            })

        enriched_roulettes.sort(key=lambda item: (-int(item.get("count") or 0), str(item.get("displayName") or item.get("name") or "")))
        _roulettes_cache["items"] = enriched_roulettes
        _roulettes_cache["expires_at"] = now + _ROULETTES_CACHE_TTL_SECONDS
        return enriched_roulettes
        
    except Exception as e:
        logging.error(f"Erro ao buscar roletas: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")

@app.get("/api/roulette/{roulette_name}/download")
async def download_roulette_data(roulette_name: str):
    """
    Baixa os dados de uma roleta específica em formato TXT
    """
    try:
        # Buscar dados da roleta
        cursor = history_coll.find(
            {"roulette_name": roulette_name}
        ).sort("timestamp", 1)
        
        results = await cursor.to_list(length=None)
        
        if not results:
            raise HTTPException(status_code=404, detail="Roleta não encontrada")
        
        # Criar conteúdo do arquivo TXT
        content_lines = [
            
        ]
        
        # Adicionar cada resultado
        for doc in results:
            timestamp = doc["timestamp"].strftime("%Y-%m-%d %H:%M:%S") if hasattr(doc["timestamp"], 'strftime') else str(doc["timestamp"])
            content_lines.append(f"{doc['value']}")
        
        content = "\n".join(content_lines)
        
        # Retornar como download de arquivo
        return Response(
            content=content,
            media_type="text/plain; charset=utf-8",
            headers={
                "Content-Disposition": f"attachment; filename=\"{roulette_name}_results.txt\""
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Erro ao gerar download: {e}")
        raise HTTPException(status_code=500, detail="Erro ao gerar arquivo")

@app.get("/api/roulette/{roulette_name}/data")
async def get_roulette_data(roulette_name: str, limit: int = 100):
    """
    Retorna dados JSON de uma roleta (para preview)
    """
    try:
        cursor = history_coll.find(
            {"roulette_name": roulette_name}
        ).sort("timestamp", -1).limit(limit)
        
        results = await cursor.to_list(length=limit)
        
        return {
            "roulette": roulette_name,
            "count": len(results),
            "data": [
                {
                    "value": doc["value"]
                }
                for doc in results
            ]
        }
        
    except Exception as e:
        logging.error(f"Erro ao buscar dados: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")
    

@app.get("/api/analise/padroes/{roulette_id}")
async def get_pattern_analysis(
    roulette_id: str,
    interval_minutes: int = 10,  # Intervalo em minutos (10, 15, 20, 30, 60)
    number: int = None,  # Número específico ou todos
    days_back: int = 30,  # Quantos dias analisar
    current_time: str = None  # Hora atual para previsão (HH:MM)
):
    """
    Análise de padrões temporais e previsão baseada em histórico
    """
    try:
        # Buscar dados históricos
        start_date = datetime.now() - timedelta(days=days_back)
        filter_query = {
            "roulette_id": roulette_id,
            "timestamp": {"$gte": start_date}
        }
        
        if number is not None:
            filter_query["value"] = number
        
        cursor = history_coll.find(filter_query).sort("timestamp", 1)
        results = await cursor.to_list(length=None)
        
        tz_br = pytz.timezone("America/Sao_Paulo")
        
        # Criar matriz de intervalos (24 horas divididas pelo intervalo)
        intervals_per_hour = 60 // interval_minutes
        total_intervals = 24 * intervals_per_hour
        
        # Estrutura para armazenar padrões
        interval_patterns = {}
        for i in range(total_intervals):
            hour = i // intervals_per_hour
            minute = (i % intervals_per_hour) * interval_minutes
            interval_key = f"{hour:02d}:{minute:02d}"
            interval_patterns[interval_key] = {
                "start_time": f"{hour:02d}:{minute:02d}",
                "end_time": f"{hour:02d}:{minute + interval_minutes - 1:02d}",
                "numbers": {},  # {numero: contagem}
                "total_occurrences": 0,
                "days_with_occurrence": set(),
                "probability": 0
            }
        
        # Processar resultados
        for doc in results:
            timestamp = doc["timestamp"]
            if timestamp.tzinfo is None:
                timestamp = pytz.utc.localize(timestamp)
            br_time = timestamp.astimezone(tz_br)
            
            # Calcular intervalo
            hour = br_time.hour
            minute = br_time.minute
            interval_index = (hour * intervals_per_hour) + (minute // interval_minutes)
            
            hour_key = hour
            minute_key = (minute // interval_minutes) * interval_minutes
            interval_key = f"{hour_key:02d}:{minute_key:02d}"
            
            if interval_key in interval_patterns:
                num = doc["value"]
                if num not in interval_patterns[interval_key]["numbers"]:
                    interval_patterns[interval_key]["numbers"][num] = 0
                interval_patterns[interval_key]["numbers"][num] += 1
                interval_patterns[interval_key]["total_occurrences"] += 1
                interval_patterns[interval_key]["days_with_occurrence"].add(br_time.date())
        
        # Calcular probabilidades e estatísticas
        for interval_key, pattern in interval_patterns.items():
            if pattern["total_occurrences"] > 0:
                pattern["probability"] = (len(pattern["days_with_occurrence"]) / days_back) * 100
                pattern["average_per_day"] = pattern["total_occurrences"] / days_back
                
                # Top 5 números mais frequentes no intervalo
                sorted_numbers = sorted(
                    pattern["numbers"].items(), 
                    key=lambda x: x[1], 
                    reverse=True
                )[:30]
                pattern["top_numbers"] = [
                    {"number": num, "count": count, "percentage": (count/pattern["total_occurrences"])*100}
                    for num, count in sorted_numbers
                ]
            else:
                pattern["probability"] = 0
                pattern["average_per_day"] = 0
                pattern["top_numbers"] = []
            
            # Converter set para list para JSON
            pattern["days_with_occurrence"] = len(pattern["days_with_occurrence"])
        
        # Análise de próximo intervalo (se current_time fornecido)
        prediction = None
        if current_time:
            try:
                hour, minute = map(int, current_time.split(":"))
                
                # Encontrar próximos intervalos
                next_intervals = []
                for i in range(3):  # Próximos 3 intervalos
                    next_minute = minute + (i * interval_minutes)
                    next_hour = hour + (next_minute // 60)
                    next_minute = next_minute % 60
                    next_hour = next_hour % 24
                    
                    interval_key = f"{next_hour:02d}:{(next_minute // interval_minutes) * interval_minutes:02d}"
                    if interval_key in interval_patterns:
                        pattern = interval_patterns[interval_key]
                        next_intervals.append({
                            "interval": interval_key,
                            "probability": pattern["probability"],
                            "historical_occurrences": pattern["total_occurrences"],
                            "top_numbers": pattern["top_numbers"],
                            "average_per_day": pattern["average_per_day"]
                        })
                
                prediction = {
                    "current_time": current_time,
                    "interval_minutes": interval_minutes,
                    "next_intervals": next_intervals
                }
            except:
                pass
        
        # Identificar hot zones (intervalos com alta frequência)
        hot_zones = []
        cold_zones = []
        
        for interval_key, pattern in interval_patterns.items():
            if pattern["probability"] > 70:  # Mais de 70% dos dias teve ocorrência
                hot_zones.append({
                    "interval": interval_key,
                    "probability": pattern["probability"],
                    "average_per_day": pattern["average_per_day"],
                    "top_numbers": pattern["top_numbers"]
                })
            elif pattern["probability"] < 10:  # Menos de 10% dos dias
                cold_zones.append({
                    "interval": interval_key,
                    "probability": pattern["probability"],
                    "total_occurrences": pattern["total_occurrences"]
                })
        
        # Ordenar zonas
        hot_zones.sort(key=lambda x: x["probability"], reverse=True)
        cold_zones.sort(key=lambda x: x["probability"])
        
        return {
            "analysis_parameters": {
                "roulette_id": roulette_id,
                "interval_minutes": interval_minutes,
                "days_analyzed": days_back,
                "total_records": len(results),
                "number_filter": number
            },
            "interval_patterns": interval_patterns,
            "hot_zones": hot_zones[:10],  # Top 10 zonas quentes
            "cold_zones": cold_zones[:10],  # Top 10 zonas frias
            "prediction": prediction
        }
        
    except Exception as e:
        logging.error(f"Erro na análise de padrões: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/analise/heatmap/{roulette_id}")
async def get_heatmap_data(
    roulette_id: str,
    days_back: int = 30
):
    """
    Gera dados para heatmap de números por hora
    """
    try:
        start_date = datetime.now() - timedelta(days=days_back)
        filter_query = {
            "roulette_id": roulette_id,
            "timestamp": {"$gte": start_date}
        }
        
        cursor = history_coll.find(filter_query)
        results = await cursor.to_list(length=None)
        
        tz_br = pytz.timezone("America/Sao_Paulo")
        
        # Criar matriz 24h x 37 números
        heatmap = {}
        for hour in range(24):
            heatmap[hour] = {}
            for num in range(37):
                heatmap[hour][num] = 0
        
        # Preencher matriz
        for doc in results:
            timestamp = doc["timestamp"]
            if timestamp.tzinfo is None:
                timestamp = pytz.utc.localize(timestamp)
            br_time = timestamp.astimezone(tz_br)
            
            hour = br_time.hour
            number = doc["value"]
            heatmap[hour][number] += 1
        
        return {
            "roulette_id": roulette_id,
            "days_analyzed": days_back,
            "heatmap_data": heatmap
        }
        
    except Exception as e:
        logging.error(f"Erro ao gerar heatmap: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/analise/tendencias/{roulette_id}")
async def get_trends_analysis(
    roulette_id: str,
    type: str = "colors",  # colors, dozens, columns
    threshold: float = 60,  # Porcentagem mínima para considerar tendência
    days_back: int = 30,  # Dias para análise
    min_duration: int = 3  # Duração mínima em minutos para considerar tendência
):
    """
    Analisa tendências minuto a minuto para identificar padrões dominantes
    """
    try:
        # Buscar dados históricos
        start_date = datetime.now() - timedelta(days=days_back)
        filter_query = {
            "roulette_id": roulette_id,
            "timestamp": {"$gte": start_date}
        }
        
        cursor = history_coll.find(filter_query).sort("timestamp", 1)
        results = await cursor.to_list(length=None)
        
        tz_br = pytz.timezone("America/Sao_Paulo")
        
        # Criar estrutura para todos os minutos do dia (1440 minutos)
        minute_analysis = {}
        for hour in range(24):
            for minute in range(60):
                key = f"{hour:02d}:{minute:02d}"
                minute_analysis[key] = {
                    "total": 0,
                    "colors": {"vermelho": 0, "preto": 0, "verde": 0},
                    "dozens": {"1ª dúzia": 0, "2ª dúzia": 0, "3ª dúzia": 0},
                    "columns": {"1ª coluna": 0, "2ª coluna": 0, "3ª coluna": 0}
                }
        
        # Processar resultados
        red_numbers = [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]
        
        for doc in results:
            timestamp = doc["timestamp"]
            if timestamp.tzinfo is None:
                timestamp = pytz.utc.localize(timestamp)
            br_time = timestamp.astimezone(tz_br)
            
            minute_key = f"{br_time.hour:02d}:{br_time.minute:02d}"
            number = doc["value"]
            
            if minute_key in minute_analysis:
                minute_analysis[minute_key]["total"] += 1
                
                # Análise de cor
                if number == 0:
                    minute_analysis[minute_key]["colors"]["verde"] += 1
                elif number in red_numbers:
                    minute_analysis[minute_key]["colors"]["vermelho"] += 1
                else:
                    minute_analysis[minute_key]["colors"]["preto"] += 1
                
                # Análise de dúzia
                if number == 0:
                    pass  # Zero não pertence a nenhuma dúzia
                elif 1 <= number <= 12:
                    minute_analysis[minute_key]["dozens"]["1ª dúzia"] += 1
                elif 13 <= number <= 24:
                    minute_analysis[minute_key]["dozens"]["2ª dúzia"] += 1
                elif 25 <= number <= 36:
                    minute_analysis[minute_key]["dozens"]["3ª dúzia"] += 1
                
                # Análise de coluna
                if number == 0:
                    pass  # Zero não pertence a nenhuma coluna
                elif number % 3 == 1:
                    minute_analysis[minute_key]["columns"]["1ª coluna"] += 1
                elif number % 3 == 2:
                    minute_analysis[minute_key]["columns"]["2ª coluna"] += 1
                elif number % 3 == 0:
                    minute_analysis[minute_key]["columns"]["3ª coluna"] += 1
        
        # Calcular porcentagens e identificar tendências
        trends = []
        current_trend = None
        
        # Escolher categoria para análise
        category = "colors" if type == "colors" else "dozens" if type == "dozens" else "columns"
        
        for minute_key in sorted(minute_analysis.keys()):
            data = minute_analysis[minute_key]
            
            if data["total"] > 0:
                # Calcular porcentagens
                percentages = {}
                for item, count in data[category].items():
                    percentages[item] = (count / data["total"]) * 100
                
                # Verificar se algum item está acima do threshold
                for item, percentage in percentages.items():
                    if percentage >= threshold:
                        if current_trend and current_trend["item"] == item:
                            # Continua a tendência atual
                            current_trend["end_time"] = minute_key
                            current_trend["minutes"].append({
                                "time": minute_key,
                                "percentage": percentage,
                                "count": data[category][item],
                                "total": data["total"]
                            })
                        else:
                            # Finaliza tendência anterior se existir
                            if current_trend and len(current_trend["minutes"]) >= min_duration:
                                trends.append(current_trend)
                            
                            # Inicia nova tendência
                            current_trend = {
                                "item": item,
                                "start_time": minute_key,
                                "end_time": minute_key,
                                "minutes": [{
                                    "time": minute_key,
                                    "percentage": percentage,
                                    "count": data[category][item],
                                    "total": data["total"]
                                }]
                            }
                        break
                else:
                    # Nenhum item acima do threshold
                    if current_trend and len(current_trend["minutes"]) >= min_duration:
                        trends.append(current_trend)
                    current_trend = None
        
        # Adicionar última tendência se existir
        if current_trend and len(current_trend["minutes"]) >= min_duration:
            trends.append(current_trend)
        
        # Processar tendências para adicionar estatísticas
        for trend in trends:
            trend["duration"] = len(trend["minutes"])
            trend["average_percentage"] = sum(m["percentage"] for m in trend["minutes"]) / len(trend["minutes"])
            trend["max_percentage"] = max(m["percentage"] for m in trend["minutes"])
            trend["total_occurrences"] = sum(m["count"] for m in trend["minutes"])
        
        # Análise estatística geral
        stats = {
            "total_trends": len(trends),
            "longest_trend": max(trends, key=lambda x: x["duration"]) if trends else None,
            "strongest_trend": max(trends, key=lambda x: x["max_percentage"]) if trends else None,
            "trend_times": {}
        }
        
        # Agrupar tendências por item
        for item in (["vermelho", "preto", "verde"] if type == "colors" else 
                    ["1ª dúzia", "2ª dúzia", "3ª dúzia"] if type == "dozens" else
                    ["1ª coluna", "2ª coluna", "3ª coluna"]):
            item_trends = [t for t in trends if t["item"] == item]
            stats["trend_times"][item] = {
                "count": len(item_trends),
                "total_minutes": sum(t["duration"] for t in item_trends),
                "average_duration": sum(t["duration"] for t in item_trends) / len(item_trends) if item_trends else 0,
                "best_times": sorted(item_trends, key=lambda x: x["average_percentage"], reverse=True)[:5]
            }
        
        return {
            "analysis_type": type,
            "threshold": threshold,
            "min_duration": min_duration,
            "days_analyzed": days_back,
            "trends": trends,
            "statistics": stats,
            "minute_data": minute_analysis
        }
        
    except Exception as e:
        logging.error(f"Erro na análise de tendências: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/analise/repeticoes/{roulette_id}")
async def get_repetitions_analysis(
    roulette_id: str,
    days_back: int = 30,
    min_repetitions: int = 2
):
    """
    Analisa repetições minuto a minuto similar à análise de tendências
    """
    try:
        # Buscar dados históricos
        start_date = datetime.now() - timedelta(days=days_back)
        filter_query = {
            "roulette_id": roulette_id,
            "timestamp": {"$gte": start_date}
        }
        
        cursor = history_coll.find(filter_query).sort("timestamp", 1)
        results = await cursor.to_list(length=None)
        
        tz_br = pytz.timezone("America/Sao_Paulo")
        
        # Estrutura para análise minuto a minuto
        minute_repetitions = {}
        for hour in range(24):
            for minute in range(60):
                key = f"{hour:02d}:{minute:02d}"
                minute_repetitions[key] = {
                    "2x": [],  # Lista de números que repetiram 2x
                    "3x": [],  # Lista de números que repetiram 3x
                    "4x": [],  # Lista de números que repetiram 4x+
                    "total": 0
                }
        
        # Analisar repetições
        i = 0
        while i < len(results) - 1:
            current = results[i]
            
            # Verificar se próximo(s) números são iguais
            repetition_count = 1
            j = i + 1
            
            while j < len(results) and results[j]["value"] == current["value"]:
                repetition_count += 1
                j += 1
            
            if repetition_count >= min_repetitions:
                # Pegar timestamp do início da repetição
                timestamp = current["timestamp"]
                if timestamp.tzinfo is None:
                    timestamp = pytz.utc.localize(timestamp)
                br_time = timestamp.astimezone(tz_br)
                
                minute_key = f"{br_time.hour:02d}:{br_time.minute:02d}"
                
                if minute_key in minute_repetitions:
                    if repetition_count == 2:
                        minute_repetitions[minute_key]["2x"].append(current["value"])
                    elif repetition_count == 3:
                        minute_repetitions[minute_key]["3x"].append(current["value"])
                    else:  # 4 ou mais
                        minute_repetitions[minute_key]["4x"].append(current["value"])
                    
                    minute_repetitions[minute_key]["total"] += 1
                
                i = j
            else:
                i += 1
        
        # Identificar horários com mais repetições
        hot_minutes = []
        for minute_key, data in minute_repetitions.items():
            if data["total"] > 0:
                hot_minutes.append({
                    "time": minute_key,
                    "total": data["total"],
                    "2x": data["2x"],
                    "3x": data["3x"],
                    "4x": data["4x"]
                })
        
        # Ordenar por total de repetições
        hot_minutes.sort(key=lambda x: x["total"], reverse=True)
        
        return {
            "days_analyzed": days_back,
            "minute_data": minute_repetitions,
            "hot_minutes": hot_minutes[:50]  # Top 50 minutos com mais repetições
        }
        
    except Exception as e:
        logging.error(f"Erro na análise de repetições: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/analise/repeticoes-padroes/{roulette_id}")
async def get_repetition_patterns(
    roulette_id: str,
    days_back: int = 30,
    time_window: int = 30,  # Janela de tempo em minutos para considerar "mesmo horário"
    include_neighbors: bool = True,  # Incluir vizinhos como repetição
    include_mirrors: bool = True  # Incluir espelhos como repetição
):
    """
    Analisa se repetições (incluindo vizinhos e espelhos) acontecem em horários similares em dias diferentes
    """
    try:
        # Buscar dados históricos
        start_date = datetime.now() - timedelta(days=days_back)
        filter_query = {
            "roulette_id": roulette_id,
            "timestamp": {"$gte": start_date}
        }
        
        cursor = history_coll.find(filter_query).sort("timestamp", 1)
        results = await cursor.to_list(length=None)
        
        tz_br = pytz.timezone("America/Sao_Paulo")
        
        # Definir vizinhos na roleta (ordem física na roleta europeia)
        neighbors = {
            0: [32, 26],
            1: [20, 33],
            2: [25, 21],
            3: [26, 35],
            4: [21, 19],
            5: [10, 24],
            6: [27, 13],
            7: [29, 28],
            8: [23, 30],
            9: [22, 31],
            10: [5, 23],
            11: [30, 36],
            12: [28, 35],
            13: [27, 6],
            14: [20, 31],
            15: [32, 19],
            16: [24, 33],
            17: [25, 34],
            18: [22, 29],
            19: [32, 15],
            20: [1, 14],
            21: [2, 4],
            22: [18, 9],
            23: [10, 8],
            24: [16, 5],
            25: [17, 2],
            26: [0, 3],
            27: [6, 13],
            28: [12, 7],
            29: [7, 18],
            30: [8, 11],
            31: [9, 14],
            32: [15, 19],
            33: [1, 16],
            34: [17, 36],
            35: [12, 3],
            36: [11, 34]
        }
        
        # Definir números espelhos
        mirrors = {
            1: [10],
            2: [20],
            3: [30],
            6: [9],
            9: [6],
            10: [1],
            11: [22, 33],
            12: [21],
            13: [31],
            16: [19],
            19: [16],
            20: [2],
            21: [12],
            22: [33, 11],
            23: [32],
            26: [29],
            29: [26],
            30: [3],
            31: [13],
            32: [23],
            33: [11, 22]
        }
        
        # Função auxiliar para verificar se é repetição
        def is_repetition(num1, num2):
            # Repetição direta
            if num1 == num2:
                return "direta"
            
            # Vizinho
            if include_neighbors and num1 in neighbors:
                if num2 in neighbors[num1]:
                    return "vizinho"
            
            # Espelho
            if include_mirrors and num1 in mirrors:
                if num2 in mirrors[num1]:
                    return "espelho"
            
            return None
        
        # Primeiro, encontrar todas as repetições
        repetitions_by_day = {}
        
        i = 0
        while i < len(results) - 1:
            current = results[i]
            next_num = results[i + 1]
            
            rep_type = is_repetition(current["value"], next_num["value"])
            
            if rep_type:
                timestamp = current["timestamp"]
                if timestamp.tzinfo is None:
                    timestamp = pytz.utc.localize(timestamp)
                br_time = timestamp.astimezone(tz_br)
                
                date_key = br_time.date().isoformat()
                time_in_minutes = br_time.hour * 60 + br_time.minute
                
                if date_key not in repetitions_by_day:
                    repetitions_by_day[date_key] = []
                
                repetitions_by_day[date_key].append({
                    "number": current["value"],
                    "next_number": next_num["value"],
                    "type": rep_type,
                    "time": f"{br_time.hour:02d}:{br_time.minute:02d}",
                    "time_minutes": time_in_minutes,
                    "full_timestamp": br_time.strftime("%d/%m/%Y %H:%M:%S")
                })
            
            i += 1
        
        # Analisar padrões de repetição por número
        pattern_analysis = {}
        
        for num in range(37):
            # Coletar todas as repetições deste número
            number_repetitions = []
            
            for date, reps in repetitions_by_day.items():
                for rep in reps:
                    if rep["number"] == num:
                        number_repetitions.append({
                            "date": date,
                            "time": rep["time"],
                            "time_minutes": rep["time_minutes"],
                            "type": rep["type"],
                            "next_number": rep["next_number"]
                        })
            
            if len(number_repetitions) >= 2:
                # Agrupar por horário similar
                time_groups = {}
                
                for rep in number_repetitions:
                    found_group = False
                    
                    for group_time, group_data in time_groups.items():
                        if abs(rep["time_minutes"] - group_time) <= time_window:
                            group_data["occurrences"].append(rep)
                            group_data["dates"].add(rep["date"])
                            group_data["types"][rep["type"]] = group_data["types"].get(rep["type"], 0) + 1
                            found_group = True
                            break
                    
                    if not found_group:
                        time_groups[rep["time_minutes"]] = {
                            "occurrences": [rep],
                            "dates": {rep["date"]},
                            "base_time": rep["time"],
                            "types": {rep["type"]: 1}
                        }
                
                # Filtrar apenas grupos com múltiplas datas
                recurring_patterns = []
                
                for group_time, group_data in time_groups.items():
                    if len(group_data["dates"]) >= 2:
                        times = [occ["time_minutes"] for occ in group_data["occurrences"]]
                        avg_time = sum(times) / len(times)
                        avg_hour = int(avg_time // 60)
                        avg_minute = int(avg_time % 60)
                        
                        # Contar tipos de repetição
                        type_summary = []
                        for t_type, count in group_data["types"].items():
                            type_summary.append(f"{t_type}: {count}")
                        
                        recurring_patterns.append({
                            "average_time": f"{avg_hour:02d}:{avg_minute:02d}",
                            "occurrences_count": len(group_data["occurrences"]),
                            "days_count": len(group_data["dates"]),
                            "dates": sorted(group_data["dates"]),
                            "details": group_data["occurrences"],
                            "probability": (len(group_data["dates"]) / days_back) * 100,
                            "type_breakdown": " | ".join(type_summary)
                        })
                
                if recurring_patterns:
                    recurring_patterns.sort(key=lambda x: x["days_count"], reverse=True)
                    pattern_analysis[num] = recurring_patterns
        
        # Criar resumo dos melhores padrões
        best_patterns = []
        for number, patterns in pattern_analysis.items():
            for pattern in patterns:
                if pattern["days_count"] >= 3:
                    best_patterns.append({
                        "number": number,
                        "time": pattern["average_time"],
                        "days_count": pattern["days_count"],
                        "total_occurrences": pattern["occurrences_count"],
                        "probability": pattern["probability"],
                        "last_dates": pattern["dates"][-3:],
                        "type_breakdown": pattern["type_breakdown"],
                        "pattern": pattern
                    })
        
        best_patterns.sort(key=lambda x: x["probability"], reverse=True)
        
        # Estatísticas gerais
        total_direct = sum(1 for _, reps in repetitions_by_day.items() for r in reps if r["type"] == "direta")
        total_neighbor = sum(1 for _, reps in repetitions_by_day.items() for r in reps if r["type"] == "vizinho")
        total_mirror = sum(1 for _, reps in repetitions_by_day.items() for r in reps if r["type"] == "espelho")
        
        return {
            "analysis_period": days_back,
            "time_window_minutes": time_window,
            "patterns_found": len(pattern_analysis),
            "best_patterns": best_patterns[:20],
            "number_patterns": pattern_analysis,
            "statistics": {
                "total_direct": total_direct,
                "total_neighbor": total_neighbor,
                "total_mirror": total_mirror,
                "include_neighbors": include_neighbors,
                "include_mirrors": include_mirrors
            }
        }
        
    except Exception as e:
        logging.error(f"Erro na análise de padrões de repetição: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/analise/sequencias/{roulette_id}")
async def get_sequences_patterns(
    roulette_id: str,
    days_back: int = 30,
    min_sequence: int = 3,  # Mínimo de números na sequência
    max_sequence: int = 7   # Máximo de números na sequência
):
    """
    Analisa sequências de números que se repetem em dias diferentes
    """
    try:
        # Buscar dados históricos
        start_date = datetime.now() - timedelta(days=days_back)
        filter_query = {
            "roulette_id": roulette_id,
            "timestamp": {"$gte": start_date}
        }
        
        cursor = history_coll.find(filter_query).sort("timestamp", 1)
        results = await cursor.to_list(length=None)
        
        if not results:
            return {"error": "Sem dados para análise"}
        
        tz_br = pytz.timezone("America/Sao_Paulo")
        
        # Dicionário para armazenar sequências encontradas
        sequences_found = {}
        
        # Percorrer os resultados para encontrar sequências
        for seq_length in range(min_sequence, max_sequence + 1):
            for i in range(len(results) - seq_length + 1):
                # Criar sequência
                sequence = []
                timestamps = []
                
                for j in range(seq_length):
                    sequence.append(results[i + j]["value"])
                    ts = results[i + j]["timestamp"]
                    if ts.tzinfo is None:
                        ts = pytz.utc.localize(ts)
                    timestamps.append(ts.astimezone(tz_br))
                
                # Criar chave da sequência
                seq_key = "-".join(map(str, sequence))
                
                # Se a sequência ainda não foi registrada, criar entrada
                if seq_key not in sequences_found:
                    sequences_found[seq_key] = {
                        "sequence": sequence,
                        "length": seq_length,
                        "occurrences": []
                    }
                
                # Adicionar ocorrência
                sequences_found[seq_key]["occurrences"].append({
                    "date": timestamps[0].date().isoformat(),
                    "start_time": timestamps[0].strftime("%H:%M:%S"),
                    "end_time": timestamps[-1].strftime("%H:%M:%S"),
                    "full_start": timestamps[0].strftime("%d/%m/%Y %H:%M:%S"),
                    "full_end": timestamps[-1].strftime("%d/%m/%Y %H:%M:%S"),
                    "hour": timestamps[0].hour,
                    "minute": timestamps[0].minute,
                    "duration_seconds": (timestamps[-1] - timestamps[0]).total_seconds()
                })
        
        # Filtrar apenas sequências que aparecem mais de uma vez
        repeated_sequences = {}
        for seq_key, data in sequences_found.items():
            if len(data["occurrences"]) >= 2:
                # Agrupar por dias diferentes
                unique_days = set()
                for occ in data["occurrences"]:
                    unique_days.add(occ["date"])
                
                if len(unique_days) >= 2:  # Apareceu em pelo menos 2 dias diferentes
                    repeated_sequences[seq_key] = {
                        "sequence": data["sequence"],
                        "length": data["length"],
                        "total_occurrences": len(data["occurrences"]),
                        "unique_days": len(unique_days),
                        "occurrences": data["occurrences"]
                    }
        
        # Analisar padrões de horário para cada sequência repetida
        patterns_with_time = []
        
        for seq_key, data in repeated_sequences.items():
            # Agrupar ocorrências por horário similar (janela de 1 hora)
            time_groups = {}
            
            for occ in data["occurrences"]:
                hour_key = occ["hour"]
                
                if hour_key not in time_groups:
                    time_groups[hour_key] = []
                
                time_groups[hour_key].append(occ)
            
            # Encontrar horário mais comum
            most_common_hour = None
            max_occurrences = 0
            
            for hour, occs in time_groups.items():
                if len(occs) > max_occurrences:
                    max_occurrences = len(occs)
                    most_common_hour = hour
            
            # Calcular estatísticas
            avg_minute = sum(occ["minute"] for occ in data["occurrences"]) // len(data["occurrences"])
            
            pattern = {
                "sequence": data["sequence"],
                "sequence_str": " → ".join(map(str, data["sequence"])),
                "length": data["length"],
                "total_occurrences": data["total_occurrences"],
                "unique_days": data["unique_days"],
                "most_common_time": f"{most_common_hour:02d}:{avg_minute:02d}",
                "probability": (data["unique_days"] / days_back) * 100,
                "occurrences_by_date": {}
            }
            
            # Organizar ocorrências por data
            for occ in data["occurrences"]:
                date = occ["date"]
                if date not in pattern["occurrences_by_date"]:
                    pattern["occurrences_by_date"][date] = []
                pattern["occurrences_by_date"][date].append({
                    "time": occ["start_time"],
                    "full_time": occ["full_start"]
                })
            
            patterns_with_time.append(pattern)
        
        # Ordenar por número de dias únicos (mais confiável)
        patterns_with_time.sort(key=lambda x: (x["unique_days"], x["total_occurrences"]), reverse=True)
        
        # Agrupar por tamanho de sequência
        sequences_by_length = {}
        for i in range(min_sequence, max_sequence + 1):
            sequences_by_length[i] = [p for p in patterns_with_time if p["length"] == i]
        
        # Encontrar as sequências mais recentes
        recent_sequences = []
        for pattern in patterns_with_time[:20]:  # Top 20
            last_occurrence = max(pattern["occurrences_by_date"].keys())
            recent_sequences.append({
                "sequence": pattern["sequence_str"],
                "last_date": last_occurrence,
                "occurrences": pattern["total_occurrences"],
                "days": pattern["unique_days"],
                "common_time": pattern["most_common_time"]
            })
        
        return {
            "analysis_period": days_back,
            "sequence_range": f"{min_sequence} a {max_sequence} números",
            "total_patterns_found": len(patterns_with_time),
            "top_patterns": patterns_with_time[:10],  # Top 10 sequências
            "sequences_by_length": sequences_by_length,
            "recent_sequences": recent_sequences
        }
        
    except Exception as e:
        logging.error(f"Erro na análise de sequências: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/analise/previsao/{roulette_id}")
async def get_prediction(
    roulette_id: str,
    time: str,  # Formato HH:MM
    interval: int = 5,  # Intervalo em minutos (5, 10, 15, 20, 30)
    days_back: int = 30  # Quantos dias analisar
):
    """
    Previsão simples: dado um horário e intervalo, retorna ranking de números mais prováveis
    """
    try:
        # Parse do horário
        hour, minute = map(int, time.split(":"))
        
        # Calcular início e fim do intervalo
        start_minute = minute - interval
        end_minute = minute + interval
        end_hour = hour
        
        if end_minute >= 60:
            end_hour = (hour + 1) % 24
            end_minute = end_minute % 60
        
        # Buscar dados históricos
        start_date = datetime.now() - timedelta(days=days_back)
        filter_query = {
            "roulette_id": roulette_id,
            "timestamp": {"$gte": start_date}
        }
        
        cursor = history_coll.find(filter_query)
        results = await cursor.to_list(length=None)
        
        tz_br = pytz.timezone("America/Sao_Paulo")
        
        # Analisar ocorrências no intervalo especificado
        numbers_count = {}
        total_in_interval = 0
        days_with_data = set()
        
        # Contadores para análises adicionais
        colors_count = {"verde": 0, "vermelho": 0, "preto": 0}
        dozens_count = {"1ª dúzia": 0, "2ª dúzia": 0, "3ª dúzia": 0, "zero": 0}
        columns_count = {"1ª coluna": 0, "2ª coluna": 0, "3ª coluna": 0, "zero": 0}
        parity_count = {"par": 0, "ímpar": 0, "zero": 0}
        half_count = {"1-18": 0, "19-36": 0, "zero": 0}
        
        for doc in results:
            timestamp = doc["timestamp"]
            if timestamp.tzinfo is None:
                timestamp = pytz.utc.localize(timestamp)
            br_time = timestamp.astimezone(tz_br)
            
            # Verificar se está no intervalo
            doc_hour = br_time.hour
            doc_minute = br_time.minute
            
            in_interval = False
            
            # Caso simples: mesmo hora
            if hour == end_hour:
                if doc_hour == hour and start_minute <= doc_minute < end_minute:
                    in_interval = True
            # Caso complexo: atravessa hora
            else:
                if (doc_hour == hour and doc_minute >= start_minute) or \
                   (doc_hour == end_hour and doc_minute < end_minute):
                    in_interval = True
            
            if in_interval:
                number = doc["value"]
                if number not in numbers_count:
                    numbers_count[number] = 0
                numbers_count[number] += 1
                total_in_interval += 1
                days_with_data.add(br_time.date())
                
                # Analisar cor
                if number == 0:
                    colors_count["verde"] += 1
                    dozens_count["zero"] += 1
                    columns_count["zero"] += 1
                    parity_count["zero"] += 1
                    half_count["zero"] += 1
                else:
                    # Cores
                    red_numbers = [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]
                    if number in red_numbers:
                        colors_count["vermelho"] += 1
                    else:
                        colors_count["preto"] += 1
                    
                    # Dúzias
                    if 1 <= number <= 12:
                        dozens_count["1ª dúzia"] += 1
                    elif 13 <= number <= 24:
                        dozens_count["2ª dúzia"] += 1
                    elif 25 <= number <= 36:
                        dozens_count["3ª dúzia"] += 1
                    
                    # Colunas
                    if number % 3 == 1:
                        columns_count["1ª coluna"] += 1
                    elif number % 3 == 2:
                        columns_count["2ª coluna"] += 1
                    elif number % 3 == 0:
                        columns_count["3ª coluna"] += 1
                    
                    # Paridade
                    if number % 2 == 0:
                        parity_count["par"] += 1
                    else:
                        parity_count["ímpar"] += 1
                    
                    # Metades
                    if number <= 18:
                        half_count["1-18"] += 1
                    else:
                        half_count["19-36"] += 1
        
        # Criar ranking
        ranking = []
        for number, count in numbers_count.items():
            percentage = (count / total_in_interval * 100) if total_in_interval > 0 else 0
            ranking.append({
                "number": number,
                "count": count,
                "percentage": percentage,
                "average_per_day": count / len(days_with_data) if days_with_data else 0
            })
        
        # Ordenar por frequência
        ranking.sort(key=lambda x: x["count"], reverse=True)
        
        # Adicionar números que nunca apareceram
        existing_numbers = {r["number"] for r in ranking}
        for num in range(37):
            if num not in existing_numbers:
                ranking.append({
                    "number": num,
                    "count": 0,
                    "percentage": 0,
                    "average_per_day": 0
                })
        
        # Calcular porcentagens para análises adicionais
        def calc_percentage(count):
            return (count / total_in_interval * 100) if total_in_interval > 0 else 0
        
        colors_analysis = {
            color: {
                "count": count,
                "percentage": calc_percentage(count)
            }
            for color, count in colors_count.items()
        }
        
        dozens_analysis = {
            dozen: {
                "count": count,
                "percentage": calc_percentage(count),
                "numbers": get_dozen_numbers(dozen)
            }
            for dozen, count in dozens_count.items()
        }
        
        columns_analysis = {
            column: {
                "count": count,
                "percentage": calc_percentage(count),
                "numbers": get_column_numbers(column)
            }
            for column, count in columns_count.items()
        }
        
        parity_analysis = {
            parity: {
                "count": count,
                "percentage": calc_percentage(count)
            }
            for parity, count in parity_count.items()
        }
        
        half_analysis = {
            half: {
                "count": count,
                "percentage": calc_percentage(count)
            }
            for half, count in half_count.items()
        }
        
        return {
            "time": time,
            "interval_minutes": interval,
            "interval_end": f"{end_hour:02d}:{end_minute:02d}",
            "days_analyzed": days_back,
            "total_occurrences_in_interval": total_in_interval,
            "days_with_occurrences": len(days_with_data),
            "ranking": ranking[:37],
            "top_5": ranking[:5],
            "bottom_5": [r for r in ranking if r["count"] == 0][:5],
            "colors": colors_analysis,
            "dozens": dozens_analysis,
            "columns": columns_analysis,
            "parity": parity_analysis,
            "half": half_analysis
        }
        
    except Exception as e:
        logging.error(f"Erro na previsão: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/analise/previsao-2/{roulette_id}")
async def get_prediction_detail(
    roulette_id: str,
    time: str,  # Formato HH:MM
    interval: int = 5,  # Intervalo em minutos (5, 10, 15, 20, 30)
    days_back: int = 30  # Quantos dias analisar
):
    """
    Previsão detalhada: dado um horário e intervalo, retorna ranking ponderado de números
    considerando número base, vizinhos e espelhos.
    """
    try:
        # Pesos (ajuste como quiser)
        WEIGHT_BASE = 3        # peso do próprio número
        WEIGHT_NEIGHBOR = 0.7    # peso dos vizinhos
        WEIGHT_MIRROR = 1.5      # peso dos espelhos

        # Parse do horário
        hour, minute = map(int, time.split(":"))
        
        # Calcular início e fim do intervalo (simples, em torno do minuto)
        start_minute = minute - interval
        end_minute = minute + interval
        end_hour = hour

        if end_minute >= 60:
            end_hour = (hour + 1) % 24
            end_minute = end_minute % 60

        # (OBS: se start_minute ficar < 0, o intervalo vai pegar a hora toda;
        # se quiser tratar isso depois, dá pra refinar essa parte.)

        # Buscar dados históricos
        start_date = datetime.now() - timedelta(days=days_back)
        filter_query = {
            "roulette_id": roulette_id,
            "timestamp": {"$gte": start_date}
        }
        
        cursor = history_coll.find(filter_query)
        results = await cursor.to_list(length=None)
        
        tz_br = pytz.timezone("America/Sao_Paulo")
        
        # Contadores
        numbers_count: dict[int, int] = {}
        weighted_scores: dict[int, float] = {}
        total_in_interval = 0
        days_with_data = set()
        
        # Contadores para análises adicionais
        colors_count = {"verde": 0, "vermelho": 0, "preto": 0}
        dozens_count = {"1ª dúzia": 0, "2ª dúzia": 0, "3ª dúzia": 0, "zero": 0}
        columns_count = {"1ª coluna": 0, "2ª coluna": 0, "3ª coluna": 0, "zero": 0}
        parity_count = {"par": 0, "ímpar": 0, "zero": 0}
        half_count = {"1-18": 0, "19-36": 0, "zero": 0}
        
        for doc in results:
            timestamp = doc["timestamp"]
            if timestamp.tzinfo is None:
                timestamp = pytz.utc.localize(timestamp)
            br_time = timestamp.astimezone(tz_br)
            
            # Verificar se está no intervalo
            doc_hour = br_time.hour
            doc_minute = br_time.minute
            
            in_interval = False
            
            # Caso simples: mesma hora
            if hour == end_hour:
                if doc_hour == hour and start_minute <= doc_minute < end_minute:
                    in_interval = True
            # Caso complexo: atravessa hora seguinte
            else:
                if (doc_hour == hour and doc_minute >= start_minute) or \
                   (doc_hour == end_hour and doc_minute < end_minute):
                    in_interval = True
            
            if not in_interval:
                continue

            number = doc["value"]

            # Contagem simples
            if number not in numbers_count:
                numbers_count[number] = 0
            numbers_count[number] += 1
            total_in_interval += 1
            days_with_data.add(br_time.date())

            # -------------------------
            # PONTUAÇÃO PONDERADA
            # -------------------------
            # Garante que todas as chaves existem
            if number not in weighted_scores:
                weighted_scores[number] = 0.0

            # 1) peso do próprio número
            weighted_scores[number] += WEIGHT_BASE

            # 2) peso dos vizinhos
            try:
                neighbors = get_neighbords(number)  # deve retornar lista de ints
            except NameError:
                neighbors = []  # se a função não estiver importada ainda
            for n in neighbors:
                if n < 0 or n > 36:
                    continue
                if n not in weighted_scores:
                    weighted_scores[n] = 0.0
                weighted_scores[n] += WEIGHT_NEIGHBOR

            # 3) peso dos espelhos
            try:
                mirrors = get_mirror(number)  # deve retornar lista de ints ou um int
            except NameError:
                mirrors = []
            if isinstance(mirrors, int):
                mirrors = [mirrors]
            for m in mirrors:
                if m < 0 or m > 36:
                    continue
                if m not in weighted_scores:
                    weighted_scores[m] = 0.0
                weighted_scores[m] += WEIGHT_MIRROR

            # -------------------------
            # Análises auxiliares (cor, dúzia, coluna, etc.)
            # -------------------------
            if number == 0:
                colors_count["verde"] += 1
                dozens_count["zero"] += 1
                columns_count["zero"] += 1
                parity_count["zero"] += 1
                half_count["zero"] += 1
            else:
                # Cores
                red_numbers = [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]
                if number in red_numbers:
                    colors_count["vermelho"] += 1
                else:
                    colors_count["preto"] += 1
                
                # Dúzias
                if 1 <= number <= 12:
                    dozens_count["1ª dúzia"] += 1
                elif 13 <= number <= 24:
                    dozens_count["2ª dúzia"] += 1
                elif 25 <= number <= 36:
                    dozens_count["3ª dúzia"] += 1
                
                # Colunas
                if number % 3 == 1:
                    columns_count["1ª coluna"] += 1
                elif number % 3 == 2:
                    columns_count["2ª coluna"] += 1
                elif number % 3 == 0:
                    columns_count["3ª coluna"] += 1
                
                # Paridade
                if number % 2 == 0:
                    parity_count["par"] += 1
                else:
                    parity_count["ímpar"] += 1
                
                # Metades
                if number <= 18:
                    half_count["1-18"] += 1
                else:
                    half_count["19-36"] += 1
        
        # Criar ranking ponderado
        ranking = []
        existing_days = len(days_with_data) if days_with_data else 0

        for num in range(37):
            count = numbers_count.get(num, 0)
            weighted_score = weighted_scores.get(num, 0.0)
            percentage = (count / total_in_interval * 100) if total_in_interval > 0 else 0.0
            avg_per_day = (count / existing_days) if existing_days > 0 else 0.0

            ranking.append({
                "number": num,
                "count": count,
                "percentage": percentage,
                "average_per_day": avg_per_day,
                "weighted_score": weighted_score
            })
        
        # Ordenar por score ponderado (desc)
        ranking.sort(key=lambda x: x["weighted_score"], reverse=True)

        # Calcular porcentagens para análises adicionais
        def calc_percentage(count: int) -> float:
            return (count / total_in_interval * 100) if total_in_interval > 0 else 0.0
        
        colors_analysis = {
            color: {
                "count": count,
                "percentage": calc_percentage(count)
            }
            for color, count in colors_count.items()
        }
        
        dozens_analysis = {
            dozen: {
                "count": count,
                "percentage": calc_percentage(count),
                "numbers": get_dozen_numbers(dozen)
            }
            for dozen, count in dozens_count.items()
        }
        
        columns_analysis = {
            column: {
                "count": count,
                "percentage": calc_percentage(count),
                "numbers": get_column_numbers(column)
            }
            for column, count in columns_count.items()
        }
        
        parity_analysis = {
            parity: {
                "count": count,
                "percentage": calc_percentage(count)
            }
            for parity, count in parity_count.items()
        }
        
        half_analysis = {
            half: {
                "count": count,
                "percentage": calc_percentage(count)
            }
            for half, count in half_count.items()
        }
        
        return {
            "time": time,
            "interval_minutes": interval,
            "interval_end": f"{end_hour:02d}:{end_minute:02d}",
            "days_analyzed": days_back,
            "total_occurrences_in_interval": total_in_interval,
            "days_with_occurrences": existing_days,
            # ranking principal já é ponderado
            "ranking": ranking,
            "top_5": ranking[:5],
            # bottom considerando menor score ponderado
            "bottom_5": list(sorted(ranking, key=lambda x: x["weighted_score"]))[:5],
            "colors": colors_analysis,
            "dozens": dozens_analysis,
            "columns": columns_analysis,
            "parity": parity_analysis,
            "half": half_analysis
        }
        
    except Exception as e:
        logging.error(f"Erro na previsão: {e}")
        raise HTTPException(status_code=500, detail=str(e))



def get_dozen_numbers(dozen):
    """Retorna os números de uma dúzia"""
    if dozen == "1ª dúzia":
        return list(range(1, 13))
    elif dozen == "2ª dúzia":
        return list(range(13, 25))
    elif dozen == "3ª dúzia":
        return list(range(25, 37))
    return [0]

def get_column_numbers(column):
    """Retorna os números de uma coluna"""
    if column == "1ª coluna":
        return [1, 4, 7, 10, 13, 16, 19, 22, 25, 28, 31, 34]
    elif column == "2ª coluna":
        return [2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32, 35]
    elif column == "3ª coluna":
        return [3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36]
    return [0]

@app.get("/api/analise/previsao-old/{roulette_id}")
async def get_prediction(
    roulette_id: str,
    time: str,  # Formato HH:MM
    interval: int = 5,  # Intervalo em minutos (5, 10, 15, 20, 30)
    days_back: int = 30  # Quantos dias analisar
):
    """
    Previsão simples: dado um horário e intervalo, retorna ranking de números mais prováveis
    """
    try:
        # Parse do horário
        hour, minute = map(int, time.split(":"))
        
        # Calcular início e fim do intervalo
        start_minute = minute
        end_minute = minute + interval
        end_hour = hour
        
        if end_minute >= 60:
            end_hour = (hour + 1) % 24
            end_minute = end_minute % 60
        
        # Buscar dados históricos
        start_date = datetime.now() - timedelta(days=days_back)
        filter_query = {
            "roulette_id": roulette_id,
            "timestamp": {"$gte": start_date}
        }
        
        cursor = history_coll.find(filter_query)
        results = await cursor.to_list(length=None)
        
        tz_br = pytz.timezone("America/Sao_Paulo")
        
        # Analisar ocorrências no intervalo especificado
        numbers_count = {}
        total_in_interval = 0
        days_with_data = set()
        
        for doc in results:
            timestamp = doc["timestamp"]
            if timestamp.tzinfo is None:
                timestamp = pytz.utc.localize(timestamp)
            br_time = timestamp.astimezone(tz_br)
            
            # Verificar se está no intervalo
            doc_hour = br_time.hour
            doc_minute = br_time.minute
            
            in_interval = False
            
            # Caso simples: mesmo hora
            if hour == end_hour:
                if doc_hour == hour and start_minute <= doc_minute < end_minute:
                    in_interval = True
            # Caso complexo: atravessa hora
            else:
                if (doc_hour == hour and doc_minute >= start_minute) or \
                   (doc_hour == end_hour and doc_minute < end_minute):
                    in_interval = True
            
            if in_interval:
                number = doc["value"]
                if number not in numbers_count:
                    numbers_count[number] = 0
                numbers_count[number] += 1
                total_in_interval += 1
                days_with_data.add(br_time.date())
        
        # Criar ranking
        ranking = []
        for number, count in numbers_count.items():
            percentage = (count / total_in_interval * 100) if total_in_interval > 0 else 0
            ranking.append({
                "number": number,
                "count": count,
                "percentage": percentage,
                "average_per_day": count / len(days_with_data) if days_with_data else 0
            })
        
        # Ordenar por frequência
        ranking.sort(key=lambda x: x["count"], reverse=True)
        
        # Adicionar números que nunca apareceram
        existing_numbers = {r["number"] for r in ranking}
        for num in range(37):
            if num not in existing_numbers:
                ranking.append({
                    "number": num,
                    "count": 0,
                    "percentage": 0,
                    "average_per_day": 0
                })
        
        return {
            "time": time,
            "interval_minutes": interval,
            "interval_end": f"{end_hour:02d}:{end_minute:02d}",
            "days_analyzed": days_back,
            "total_occurrences_in_interval": total_in_interval,
            "days_with_occurrences": len(days_with_data),
            "ranking": ranking[:37],  # Top 37 (todos os números)
            "top_5": ranking[:5],  # Top 5 mais prováveis
            "bottom_5": [r for r in ranking if r["count"] == 0][:5]  # 5 que nunca apareceram
        }
        
    except Exception as e:
        logging.error(f"Erro na previsão: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/download-all")
async def download_all_roulettes():
    """
    Baixa todas as roletas Pragmatic em um arquivo ZIP
    """
    try:
        # Obter lista de todas as roletas Pragmatic
        roulettes_cursor = history_coll.distinct("roulette_name", {"roulette_id": {"$regex": "pragmatic", "$options": "i"}})
        roulette_names = await roulettes_cursor
        
        # Criar arquivo ZIP em memória
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            
            for roulette_name in roulette_names:
                # Buscar dados da roleta
                cursor = history_coll.find(
                    {"roulette_name": roulette_name}
                ).sort("timestamp", 1)
                
                results = await cursor.to_list(length=None)
                
                # Criar conteúdo do arquivo TXT
                content_lines = []
                
                for doc in results:
                    timestamp = doc["timestamp"].strftime("%Y-%m-%d %H:%M:%S") if hasattr(doc["timestamp"], 'strftime') else str(doc["timestamp"])
                    content_lines.append(f"{doc['value']}")
                
                content = "\n".join(content_lines)
                
                # Adicionar arquivo ao ZIP
                zip_file.writestr(f"{roulette_name}_results.txt", content)
        
        zip_buffer.seek(0)
        
        # Retornar ZIP como stream
        return StreamingResponse(
            io.BytesIO(zip_buffer.getvalue()),
            media_type="application/zip",
            headers={
                "Content-Disposition": "attachment; filename=\"todas_roletas_pragmatic.zip\""
            }
        )
        
    except Exception as e:
        logging.error(f"Erro ao criar ZIP: {e}")
        raise HTTPException(status_code=500, detail="Erro ao criar ZIP")

# Funções auxiliares (adicione no final do arquivo)




@app.get("/api/analise/numeros-puxados/{roulette_id}")
async def get_pull_numbers_analysis(
    roulette_id: str,
    numero: int,  # Número base para análise
    profundidade: int = 5,  # Quantos números olhar após (default: 5)
    days_back: int = 30,  # Dias para analisar
    min_ocorrencias: int = 50  # Mínimo de ocorrências para considerar confiável
):
    """
    Analisa quais números mais aparecem após um número específico ser sorteado.
    
    Exemplo: Após o 24, quais números mais saem?
    
    Params:
    - roulette_id: ID da roleta
    - numero: Número base (0-36)
    - profundidade: Quantos números olhar após cada ocorrência (padrão: 5)
    - days_back: Quantos dias analisar (padrão: 30)
    - min_ocorrencias: Mínimo de ocorrências para alta confiança (padrão: 50)
    """
    try:
        # Validação
        if not (0 <= numero <= 36):
            raise HTTPException(status_code=400, detail="Número deve estar entre 0 e 36")
        
        if profundidade < 1 or profundidade > 20:
            raise HTTPException(status_code=400, detail="Profundidade deve estar entre 1 e 20")
        
        # Buscar dados históricos
        start_date = datetime.now() - timedelta(days=days_back)
        filter_query = {
            "roulette_id": roulette_id,
            "timestamp": {"$gte": start_date}
        }
        
        cursor = history_coll.find(filter_query).sort("timestamp", 1)
        results = await cursor.to_list(length=None)
        
        if len(results) < profundidade:
            return {
                "erro": "Dados insuficientes para análise",
                "total_resultados": len(results)
            }
        
        tz_br = pytz.timezone("America/Sao_Paulo")
        
        # ==================================================
        # 1. ENCONTRAR TODAS AS OCORRÊNCIAS DO NÚMERO
        # ==================================================
        ocorrencias = []
        
        for i in range(len(results) - profundidade):
            if results[i]["value"] == numero:
                # Pegar próximos N números
                proximos = []
                timestamps = []
                
                for j in range(1, profundidade + 1):
                    if i + j < len(results):
                        proximos.append(results[i + j]["value"])
                        
                        ts = results[i + j]["timestamp"]
                        if ts.tzinfo is None:
                            ts = pytz.utc.localize(ts)
                        timestamps.append(ts.astimezone(tz_br))
                
                if len(proximos) == profundidade:
                    timestamp = results[i]["timestamp"]
                    if timestamp.tzinfo is None:
                        timestamp = pytz.utc.localize(timestamp)
                    br_time = timestamp.astimezone(tz_br)
                    
                    ocorrencias.append({
                        "indice": i,
                        "timestamp": br_time.strftime("%Y-%m-%d %H:%M:%S"),
                        "proximos_numeros": proximos,
                        "hora": br_time.hour,
                        "data": br_time.date().isoformat()
                    })
        
        # Verificar se há ocorrências suficientes
        if len(ocorrencias) < min_ocorrencias:
            confianca = "baixa"
            aviso = f"Apenas {len(ocorrencias)} ocorrências encontradas. Recomendado: {min_ocorrencias}+"
        else:
            confianca = "alta" if len(ocorrencias) >= 100 else "media"
            aviso = None
        
        # ==================================================
        # 2. CONTAR FREQUÊNCIA DOS NÚMEROS QUE VIERAM DEPOIS
        # ==================================================
        contagem_geral = {}
        contagem_por_posicao = {}  # {numero: [freq_pos1, freq_pos2, ...]}
        
        for occ in ocorrencias:
            for posicao, num in enumerate(occ["proximos_numeros"]):
                # Contagem geral
                contagem_geral[num] = contagem_geral.get(num, 0) + 1
                
                # Contagem por posição
                if num not in contagem_por_posicao:
                    contagem_por_posicao[num] = [0] * profundidade
                contagem_por_posicao[num][posicao] += 1
        
        # ==================================================
        # 3. CRIAR RANKING ORDENADO
        # ==================================================
        total_analisado = len(ocorrencias) * profundidade
        
        ranking = []
        for num, freq in contagem_geral.items():
            percentual = (freq / total_analisado) * 100
            forca = freq / len(ocorrencias)  # Média de vezes por ocorrência
            
            ranking.append({
                "numero": num,
                "frequencia": freq,
                "percentual": round(percentual, 2),
                "forca": round(forca, 2),
                "distribuicao": contagem_por_posicao[num]
            })
        
        # Ordenar por frequência
        ranking.sort(key=lambda x: x["frequencia"], reverse=True)
        
        # ==================================================
        # 4. ANÁLISE TEMPORAL (ÚLTIMAS 500 RODADAS)
        # ==================================================
        historico_recente = results[-500:] if len(results) > 500 else results
        ocorrencias_recentes = []
        
        for i in range(len(historico_recente) - profundidade):
            if historico_recente[i]["value"] == numero:
                proximos = [historico_recente[i + j]["value"] for j in range(1, profundidade + 1) 
                           if i + j < len(historico_recente)]
                if len(proximos) == profundidade:
                    ocorrencias_recentes.append(proximos)
        
        ranking_recente = {}
        for nums in ocorrencias_recentes:
            for n in nums:
                ranking_recente[n] = ranking_recente.get(n, 0) + 1
        
        top5_recente = sorted(
            [{"numero": num, "frequencia": freq} for num, freq in ranking_recente.items()],
            key=lambda x: x["frequencia"],
            reverse=True
        )[:5]
        
        # ==================================================
        # 5. ESTATÍSTICAS E TOP 5
        # ==================================================
        top5 = ranking[:5]
        media_frequencia = sum(r["frequencia"] for r in ranking) / len(ranking) if ranking else 0
        soma_top5 = sum(r["frequencia"] for r in top5)
        concentracao_top5 = (soma_top5 / total_analisado * 100) if total_analisado > 0 else 0
        
        # ==================================================
        # 6. INSIGHTS AUTOMÁTICOS
        # ==================================================
        insights = []
        
        if confianca == "alta":
            insights.append(f"✅ ALTA CONFIANÇA: {numero} tem padrão forte com {len(ocorrencias)}+ ocorrências")
        
        if top5:
            primeiro = top5[0]
            insights.append(
                f"🎯 Após {numero}, o número {primeiro['numero']} aparece "
                f"{primeiro['frequencia']}x ({primeiro['percentual']}%)"
            )
        
        if len(top5) >= 3:
            nums = ", ".join(str(r["numero"]) for r in top5[:3])
            insights.append(f"📊 Top 3 puxados: {nums}")
        
        # Verificar números com força > 1.0
        numero_forte = next((r for r in top5 if r["forca"] > 1.0), None)
        if numero_forte:
            insights.append(
                f"⚡ {numero_forte['numero']} tem força {numero_forte['forca']}x (muito frequente!)"
            )
        
        # Analisar distribuição por posição
        for r in top5[:3]:
            pos_max = r["distribuicao"].index(max(r["distribuicao"]))
            if max(r["distribuicao"]) / r["frequencia"] > 0.4:  # > 40% em uma posição
                insights.append(
                    f"📍 {r['numero']} aparece mais na posição {pos_max + 1} "
                    f"após {numero} ({r['distribuicao'][pos_max]}x)"
                )
        
        # ==================================================
        # 7. ANÁLISE POR HORÁRIO (BÔNUS)
        # ==================================================
        horarios_quentes = {}
        for occ in ocorrencias:
            hora = occ["hora"]
            if hora not in horarios_quentes:
                horarios_quentes[hora] = 0
            horarios_quentes[hora] += 1
        
        top_horarios = sorted(
            [{"hora": f"{h:02d}:00", "ocorrencias": c} for h, c in horarios_quentes.items()],
            key=lambda x: x["ocorrencias"],
            reverse=True
        )[:5]
        
        # ==================================================
        # 8. RESPOSTA FINAL
        # ==================================================
        return {
            "numero_analisado": numero,
            "roulette_id": roulette_id,
            "profundidade": profundidade,
            
            "estatisticas": {
                "total_ocorrencias": len(ocorrencias),
                "total_analisado": total_analisado,
                "media_frequencia": round(media_frequencia, 2),
                "concentracao_top5": round(concentracao_top5, 2),
                "confianca": confianca,
                "aviso": aviso
            },
            
            "ranking": ranking[:20],  # Top 20
            "top5": top5,
            
            "analise_recente": {
                "descricao": "Últimas 500 rodadas",
                "ocorrencias": len(ocorrencias_recentes),
                "top5": top5_recente
            },
            
            "horarios_quentes": top_horarios,
            "insights": insights,
            
            # Dados extras para análise detalhada
            "dias_analisados": days_back,
            "periodo": {
                "inicio": results[0]["timestamp"].strftime("%Y-%m-%d") if results else None,
                "fim": results[-1]["timestamp"].strftime("%Y-%m-%d") if results else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Erro na análise de números puxados: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/analise/numeros-puxados-lote/{roulette_id}")
async def get_pull_numbers_batch(
    roulette_id: str,
    numeros: str,  # Lista separada por vírgula: "10,24,33"
    profundidade: int = 5,
    days_back: int = 30
):
    """
    Analisa múltiplos números de uma vez.
    
    Exemplo: /api/analise/numeros-puxados-lote/pragmatic-brazilian-roulette?numeros=10,24,33
    """
    try:
        # Parse dos números
        lista_numeros = [int(n.strip()) for n in numeros.split(",")]
        
        # Validação
        if len(lista_numeros) > 10:
            raise HTTPException(status_code=400, detail="Máximo 10 números por vez")
        
        for num in lista_numeros:
            if not (0 <= num <= 36):
                raise HTTPException(status_code=400, detail=f"Número {num} inválido")
        
        # Analisar cada número
        resultados = {}
        
        for numero in lista_numeros:
            # Reusar a função anterior
            analise = await get_pull_numbers_analysis(
                roulette_id=roulette_id,
                numero=numero,
                profundidade=profundidade,
                days_back=days_back,
                min_ocorrencias=30  # Menor threshold para análise em lote
            )
            
            # Simplificar resposta
            resultados[numero] = {
                "confianca": analise["estatisticas"]["confianca"],
                "total_ocorrencias": analise["estatisticas"]["total_ocorrencias"],
                "top3": analise["top5"][:3],
                "insight_principal": analise["insights"][0] if analise["insights"] else None
            }
        
        return {
            "roulette_id": roulette_id,
            "numeros_analisados": lista_numeros,
            "total_numeros": len(lista_numeros),
            "resultados": resultados
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Erro na análise em lote: {e}")
        raise HTTPException(status_code=500, detail=str(e))



from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import pytz

@app.get("/api/ensemble/sugestao-completa/{roulette_id}")
async def get_complete_ensemble_suggestion(
    roulette_id: str,
    limite: int = 12,
    days_back: int = 30,
    profundidade_puxadas: int = 5,
    modo: str = "equilibrado",
    horario_atual: Optional[str] = None
):
    """
    🎯 ENSEMBLE MASTER COMPLETO - Lógica Melhorada
    
    Combina 5 filtros com pesos inteligentes:
    1. Master (padrões exatos com janelas)
    2. Estelar (espelhos, vizinhos, terminal, soma, retornos)
    3. Chain (cadeias comportamentais e faltantes)
    4. Temporal (recorrência por horário)
    5. Puxadas (análise estatística de sequências)
    """
    try:
        # =============================================
        # CONSTANTES
        # =============================================
        ESPELHOS = {
            1:10, 10:1, 2:20, 20:2, 3:30, 30:3,
            6:9, 9:6, 16:19, 19:16, 26:29, 29:26,
            13:31, 31:13, 12:21, 21:12, 32:23, 23:32
        }
        
        RODA = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]
        
        # Pesos por modo
        PESOS_MODOS = {
            "equilibrado": {"puxadas": 0.20, "temporal": 0.20, "master": 0.20, "estelar": 0.20, "chain": 0.20},
            "conservador": {"puxadas": 0.35, "temporal": 0.35, "master": 0.10, "estelar": 0.10, "chain": 0.10},
            "agressivo": {"puxadas": 0.10, "temporal": 0.10, "master": 0.25, "estelar": 0.25, "chain": 0.30},
            "temporal": {"puxadas": 0.15, "temporal": 0.50, "master": 0.10, "estelar": 0.15, "chain": 0.10},
            "chain": {"puxadas": 0.15, "temporal": 0.10, "master": 0.15, "estelar": 0.20, "chain": 0.40}
        }
        
        pesos = PESOS_MODOS.get(modo, PESOS_MODOS["equilibrado"])
        
        # =============================================
        # FUNÇÕES AUXILIARES
        # =============================================
        def get_vizinhos(n: int) -> List[int]:
            if n not in RODA:
                return []
            idx = RODA.index(n)
            return [RODA[(idx - 1 + 37) % 37], RODA[(idx + 1) % 37]]
        
        def get_terminal(n: int) -> int:
            return n % 10
        
        def get_soma(n: int) -> int:
            return (n // 10) + (n % 10)
        
        # =============================================
        # CARREGAR HISTÓRICO
        # =============================================
        start_date = datetime.now() - timedelta(days=days_back)
        filter_query = {
            "roulette_id": roulette_id,
            "timestamp": {"$gte": start_date}
        }
        
        cursor = history_coll.find(filter_query).sort("timestamp", -1)
        results = await cursor.to_list(length=None)
        
        if len(results) < 50:
            raise HTTPException(status_code=400, detail="Histórico insuficiente (mínimo 50)")
        
        historico = [doc["value"] for doc in results]
        ultimo_numero = historico[0]
        
        # =============================================
        # 1. FILTRO ESTELAR (Lógica Melhorada)
        # =============================================
        def analisar_estelar_melhorado(hist: List[int]) -> Dict:
            scores = {}
            ctx = hist[:30]  # Contexto de 30 números
            recente = ctx[0]
            
            # 1.1 ESPELHOS DO CONTEXTO (não só do último)
            espelhos_ctx = set()
            for n in ctx[:20]:
                if n in ESPELHOS:
                    espelhos_ctx.add(ESPELHOS[n])
            
            for esp in espelhos_ctx:
                scores[esp] = scores.get(esp, 0) + 10
            
            # 1.2 RETORNOS FREQUENTES (apareceram 2+ vezes no contexto)
            freq = {}
            for n in ctx:
                freq[n] = freq.get(n, 0) + 1
            
            retornos = sorted(
                [(n, f) for n, f in freq.items() if f >= 2],
                key=lambda x: x[1],
                reverse=True
            )
            
            for i, (num, frequencia) in enumerate(retornos):
                pontos = max(10 - i, 1) + (frequencia - 1)  # Bônus por frequência
                scores[num] = scores.get(num, 0) + pontos
            
            # 1.3 FAMÍLIA DO TERMINAL (todos do mesmo terminal)
            terminal = get_terminal(recente)
            for i in range(terminal, 37, 10):
                if i >= 0 and i != recente:
                    scores[i] = scores.get(i, 0) + 5
            
            # 1.4 NÚMEROS POR SOMA (mesma soma de dígitos)
            soma_recente = get_soma(recente)
            for i in range(1, 37):
                if get_soma(i) == soma_recente and i not in ctx[:20]:
                    scores[i] = scores.get(i, 0) + 5
            
            # 1.5 VIZINHOS DO ÚLTIMO
            vizinhos = get_vizinhos(recente)
            for viz in vizinhos:
                scores[viz] = scores.get(viz, 0) + 7
            
            # 1.6 ESPELHO DIRETO DO ÚLTIMO (peso extra)
            if recente in ESPELHOS:
                scores[ESPELHOS[recente]] = scores.get(ESPELHOS[recente], 0) + 8
            
            return {
                "scores": scores,
                "espelhos_contexto": list(espelhos_ctx),
                "retornos_frequentes": [n for n, _ in retornos[:5]],
                "familia_terminal": [i for i in range(terminal, 37, 10) if i >= 0 and i != recente],
                "vizinhos": vizinhos
            }
        
        # =============================================
        # 2. FILTRO MASTER (Padrões Exatos Melhorado)
        # =============================================
        def analisar_master_melhorado(hist: List[int]) -> Dict:
            scores = {}
            janelas_testadas = [2, 3, 4]  # Testar múltiplos tamanhos de janela
            
            for tamanho_janela in janelas_testadas:
                # Buscar padrões no histórico recente
                for i in range(min(50, len(hist) - tamanho_janela)):
                    padrao_atual = tuple(hist[i:i + tamanho_janela])
                    
                    # Buscar esse padrão no resto do histórico
                    for j in range(i + tamanho_janela, min(200, len(hist) - 1)):
                        padrao_comparacao = tuple(hist[j:j + tamanho_janela])
                        
                        if padrao_atual == padrao_comparacao:
                            if j + tamanho_janela < len(hist):
                                proximo = hist[j + tamanho_janela]
                                # Peso maior para janelas maiores e padrões mais recentes
                                peso = tamanho_janela * (1.0 / (1 + i * 0.1))
                                scores[proximo] = scores.get(proximo, 0) + peso
            
            return {
                "scores": scores,
                "padroes_encontrados": len([s for s in scores.values() if s > 0])
            }
        
        # =============================================
        # 3. FILTRO CHAIN (Cadeias e Faltantes Melhorado)
        # =============================================
        def analisar_chain_melhorado(hist: List[int]) -> Dict:
            scores = {}
            faltantes = []
            
            # 3.1 DETECTAR PUXADAS RECORRENTES (X → Y acontece 2+ vezes)
            cadeias = {}
            for i in range(min(150, len(hist) - 1)):
                chave = f"{hist[i]}->{hist[i+1]}"
                cadeias[chave] = cadeias.get(chave, 0) + 1
            
            cadeias_fortes = {k: v for k, v in cadeias.items() if v >= 2}
            
            # 3.2 ANALISAR ÚLTIMOS 5 NÚMEROS
            ultimos_5 = hist[:5]
            
            # Verificar se há cadeias ativas
            for i in range(len(ultimos_5) - 1):
                chave = f"{ultimos_5[i]}->{ultimos_5[i+1]}"
                
                if chave in cadeias_fortes:
                    # Procurar o que normalmente vem depois
                    for j in range(len(hist) - 2):
                        if hist[j] == ultimos_5[i] and hist[j+1] == ultimos_5[i+1]:
                            if j + 2 < len(hist):
                                proximo = hist[j + 2]
                                peso = cadeias_fortes[chave] * 4
                                scores[proximo] = scores.get(proximo, 0) + peso
                                if proximo not in faltantes:
                                    faltantes.append(proximo)
            
            # 3.3 DETECTAR FALTANTES POR VIZINHANÇA
            # Ex: 27-11-36 são vizinhos do 13, mas 13 não apareceu
            for num in range(37):
                if num not in RODA:
                    continue
                
                idx = RODA.index(num)
                viz_esq = RODA[(idx - 1 + 37) % 37]
                viz_dir = RODA[(idx + 1) % 37]
                
                # Verificar se vizinhos aparecem mas o número não
                if viz_esq in ultimos_5 and viz_dir in ultimos_5:
                    if num not in hist[:15]:
                        scores[num] = scores.get(num, 0) + 10
                        if num not in faltantes:
                            faltantes.append(num)
            
            # 3.4 ESPELHOS QUE FALTAM
            # Se um número apareceu recentemente, seu espelho pode estar devendo
            for num in ultimos_5[:3]:
                if num in ESPELHOS:
                    espelho = ESPELHOS[num]
                    if espelho not in hist[:20]:
                        scores[espelho] = scores.get(espelho, 0) + 6
                        if espelho not in faltantes:
                            faltantes.append(espelho)
            
            return {
                "scores": scores,
                "cadeias_detectadas": len(cadeias_fortes),
                "faltantes": faltantes[:5]
            }
        
        # =============================================
        # 4. FILTRO TEMPORAL
        # =============================================
        async def analisar_temporal_melhorado(
            roulette_id: str, 
            horario: str, 
            results: List
        ) -> Dict:
            try:
                if not horario:
                    return {"scores": {}, "total_no_intervalo": 0}
                
                hour, minute = map(int, horario.split(":"))
                intervalo = 10  # ±10 minutos
                
                tz_br = pytz.timezone("America/Sao_Paulo")
                contagem = {}
                total_no_intervalo = 0
                
                for doc in results:
                    timestamp = doc["timestamp"]
                    if timestamp.tzinfo is None:
                        timestamp = pytz.utc.localize(timestamp)
                    br_time = timestamp.astimezone(tz_br)
                    
                    # Calcular diferença em minutos
                    diff_minutos = abs((br_time.hour * 60 + br_time.minute) - (hour * 60 + minute))
                    
                    if diff_minutos <= intervalo:
                        num = doc["value"]
                        contagem[num] = contagem.get(num, 0) + 1
                        total_no_intervalo += 1
                
                # Calcular scores normalizados
                scores = {}
                if total_no_intervalo > 0:
                    for num, freq in contagem.items():
                        scores[num] = (freq / total_no_intervalo) * 100
                
                return {
                    "scores": scores,
                    "total_no_intervalo": total_no_intervalo,
                    "intervalo": f"{horario} ±{intervalo}min"
                }
            except Exception as e:
                logging.error(f"Erro no filtro temporal: {e}")
                return {"scores": {}, "total_no_intervalo": 0}
        
        # =============================================
        # 5. FILTRO DE PUXADAS
        # =============================================
        async def analisar_puxadas_melhorado(
            roulette_id: str,
            numero: int,
            profundidade: int,
            results: List
        ) -> Dict:
            ocorrencias = []
            
            for i in range(len(results) - profundidade):
                if results[i]["value"] == numero:
                    proximos = [results[i + j]["value"] for j in range(1, profundidade + 1)
                               if i + j < len(results)]
                    if len(proximos) == profundidade:
                        ocorrencias.append(proximos)
            
            contagem = {}
            for occ in ocorrencias:
                for num in occ:
                    contagem[num] = contagem.get(num, 0) + 1
            
            total = len(ocorrencias) * profundidade if ocorrencias else 1
            
            # Calcular força (média de aparições por ocorrência)
            scores = {}
            for num, freq in contagem.items():
                forca = freq / len(ocorrencias) if ocorrencias else 0
                scores[num] = forca * 100  # Normalizar para 0-100
            
            return {
                "scores": scores,
                "ocorrencias": len(ocorrencias),
                "confianca": "alta" if len(ocorrencias) >= 100 else "media" if len(ocorrencias) >= 50 else "baixa"
            }
        
        # =============================================
        # EXECUTAR ANÁLISES
        # =============================================
        estelar_result = analisar_estelar_melhorado(historico)
        master_result = analisar_master_melhorado(historico)
        chain_result = analisar_chain_melhorado(historico)
        temporal_result = await analisar_temporal_melhorado(roulette_id, horario_atual, results)
        puxadas_result = await analisar_puxadas_melhorado(roulette_id, ultimo_numero, profundidade_puxadas, results)
        
        # =============================================
        # NORMALIZAR SCORES (0-100)
        # =============================================
        def normalizar(scores_dict: Dict) -> Dict:
            if not scores_dict:
                return {}
            max_score = max(scores_dict.values())
            if max_score == 0:
                return {}
            return {num: (score / max_score) * 100 for num, score in scores_dict.items()}
        
        estelar_norm = normalizar(estelar_result["scores"])
        master_norm = normalizar(master_result["scores"])
        chain_norm = normalizar(chain_result["scores"])
        temporal_norm = normalizar(temporal_result["scores"])
        puxadas_norm = normalizar(puxadas_result["scores"])
        
        # =============================================
        # COMBINAR ENSEMBLE
        # =============================================
        ensemble_scores = {}
        detalhes_por_numero = {}
        
        for num in range(37):
            score_total = 0
            filtros_ativos = []
            contribuicoes = {}
            
            # Aplicar pesos
            if num in estelar_norm:
                contrib = estelar_norm[num] * pesos["estelar"]
                score_total += contrib
                filtros_ativos.append("estelar")
                contribuicoes["estelar"] = round(contrib, 2)
            
            if num in master_norm:
                contrib = master_norm[num] * pesos["master"]
                score_total += contrib
                filtros_ativos.append("master")
                contribuicoes["master"] = round(contrib, 2)
            
            if num in chain_norm:
                contrib = chain_norm[num] * pesos["chain"]
                score_total += contrib
                filtros_ativos.append("chain")
                contribuicoes["chain"] = round(contrib, 2)
            
            if num in temporal_norm:
                contrib = temporal_norm[num] * pesos["temporal"]
                score_total += contrib
                filtros_ativos.append("temporal")
                contribuicoes["temporal"] = round(contrib, 2)
            
            if num in puxadas_norm:
                contrib = puxadas_norm[num] * pesos["puxadas"]
                score_total += contrib
                filtros_ativos.append("puxadas")
                contribuicoes["puxadas"] = round(contrib, 2)
            
            # BÔNUS DE CONSENSO (se múltiplos filtros concordam)
            if len(filtros_ativos) >= 3:
                score_total *= 1.2  # 20% de bônus
            if len(filtros_ativos) >= 4:
                score_total *= 1.3  # 30% adicional
            
            if score_total > 0:
                ensemble_scores[num] = score_total
                detalhes_por_numero[num] = {
                    "filtros_ativos": filtros_ativos,
                    "contribuicoes": contribuicoes
                }
        
        # =============================================
        # CRIAR RANKING
        # =============================================
        def calcular_confianca(qtd_filtros: int) -> str:
            if qtd_filtros >= 4:
                return "muito_alta"
            elif qtd_filtros >= 3:
                return "alta"
            elif qtd_filtros >= 2:
                return "media"
            else:
                return "baixa"
        
        ranking = sorted(
            [
                {
                    "numero": num,
                    "score": round(score, 2),
                    "confianca": calcular_confianca(len(detalhes_por_numero[num]["filtros_ativos"])),
                    "detalhes": detalhes_por_numero[num]
                }
                for num, score in ensemble_scores.items()
            ],
            key=lambda x: x["score"],
            reverse=True
        )[:limite]
        
        # =============================================
        # ANÁLISE DE CONSENSO
        # =============================================
        consenso_forte = [r["numero"] for r in ranking if len(r["detalhes"]["filtros_ativos"]) >= 4]
        consenso_medio = [r["numero"] for r in ranking if len(r["detalhes"]["filtros_ativos"]) == 3]
        
        # =============================================
        # PROTEÇÕES
        # =============================================
        protecoes = set([r["numero"] for r in ranking])
        protecoes.add(0)  # Sempre incluir zero 
        
        # Espelhos das top 3
        for num in [r["numero"] for r in ranking[:3]]:
            if num in ESPELHOS:
                protecoes.add(ESPELHOS[num])
        
        # =============================================
        # INSIGHTS
        # =============================================
        insights = []
        
        if ranking:
            top1 = ranking[0]
            insights.append(
                f"🎯 Número mais provável: {top1['numero']} "
                f"(score {top1['score']}, confiança {top1['confianca']})"
            )
            
            qtd = len(top1['detalhes']['filtros_ativos'])
            if qtd >= 4:
                insights.append(f"⭐ {top1['numero']} tem consenso de {qtd}/5 filtros!")
        
        if consenso_forte:
            insights.append(f"🔥 Consenso forte (4+ filtros): {', '.join(map(str, consenso_forte[:3]))}")
        
        if puxadas_result["confianca"] == "alta":
            insights.append(f"✅ Filtro de puxadas com alta confiança ({puxadas_result['ocorrencias']}+ ocorrências)")
        
        if temporal_result["total_no_intervalo"] > 50:
            insights.append(f"⏰ Padrão temporal forte: {temporal_result['total_no_intervalo']} ocorrências no horário")
        
        if chain_result["faltantes"]:
            insights.append(f"⛓️ Faltantes detectados: {', '.join(map(str, chain_result['faltantes'][:3]))}")
        
        # =============================================
        # RESPOSTA FINAL
        # =============================================
        return {
            "roulette_id": roulette_id,
            "ultimo_numero": ultimo_numero,
            "horario_analise": horario_atual or "N/A",
            "modo": modo,
            "dias_analisados": days_back,
            
            "sugestoes": {
                "top_3": [r["numero"] for r in ranking[:3]],
                "top_5": [r["numero"] for r in ranking[:5]],
                "completo": [r["numero"] for r in ranking],
                "com_protecoes": sorted(list(protecoes))[:18]
            },
            
            "ranking_detalhado": ranking,
            
            "analise_filtros": {
                
                "temporal": {
                    "top_3": sorted(temporal_norm.items(), key=lambda x: x[1], reverse=True)[:10],
                    "intervalo": temporal_result.get("intervalo", "N/A")
                },
                "master": {
                    "padroes_encontrados": master_result["padroes_encontrados"],
                    "top_3": sorted(master_norm.items(), key=lambda x: x[1], reverse=True)[:10]
                },
                "estelar": {
                    "equivalencias_encontradas": len(estelar_norm),
                    "top_3": sorted(estelar_norm.items(), key=lambda x: x[1], reverse=True)[:10]
                },
                "chain": {
                    "cadeias_detectadas": chain_result["cadeias_detectadas"],
                    "faltantes": chain_result["faltantes"],
                    "top_3": sorted(chain_norm.items(), key=lambda x: x[1], reverse=True)[:10]
                }
            },
            
            "consenso": {
                "consenso_forte": consenso_forte[:5],
                "consenso_medio": consenso_medio[:5],
                "total_com_consenso": len(consenso_forte) + len(consenso_medio)
            },
            
            "configuracao": {
                "modo": modo,
                "pesos": pesos,
                "limite": limite
            },
            
            "insights": insights
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Erro no ensemble completo: {e}")
        raise HTTPException(status_code=500, detail=str(e))
        
# =============================================
# FUNÇÕES AUXILIARES - ANÁLISE DE CADA FILTRO
# =============================================

async def analisar_puxadas(roulette_id: str, numero: int, profundidade: int, results: List) -> Dict:
    """Análise do filtro de puxadas"""
    ocorrencias = []
    
    for i in range(len(results) - profundidade):
        if results[i]["value"] == numero:
            proximos = [results[i + j]["value"] for j in range(1, profundidade + 1) 
                       if i + j < len(results)]
            if len(proximos) == profundidade:
                ocorrencias.append(proximos)
    
    contagem = {}
    for occ in ocorrencias:
        for num in occ:
            contagem[num] = contagem.get(num, 0) + 1
    
    total = len(ocorrencias) * profundidade if ocorrencias else 1
    
    return {
        "scores": {num: (freq / total) * 100 for num, freq in contagem.items()},
        "ocorrencias": len(ocorrencias),
        "confianca": "alta" if len(ocorrencias) >= 100 else "media" if len(ocorrencias) >= 50 else "baixa"
    }


async def analisar_temporal(roulette_id: str, horario: str, results: List) -> Dict:
    """Análise do filtro temporal"""
    try:
        hour, minute = map(int, horario.split(":"))
        intervalo = 5  # Janela de ±10 minutos
        
        tz_br = pytz.timezone("America/Sao_Paulo")
        contagem = {}
        total_no_intervalo = 0
        
        for doc in results:
            timestamp = doc["timestamp"]
            if timestamp.tzinfo is None:
                timestamp = pytz.utc.localize(timestamp)
            br_time = timestamp.astimezone(tz_br)
            
            # Verificar se está no intervalo
            diff_minutos = abs((br_time.hour * 60 + br_time.minute) - (hour * 60 + minute))
            
            if diff_minutos <= intervalo:
                num = doc["value"]
                contagem[num] = contagem.get(num, 0) + 1
                total_no_intervalo += 1
        
        return {
            "scores": {num: (freq / total_no_intervalo) * 100 for num, freq in contagem.items()} if total_no_intervalo > 0 else {},
            "total_no_intervalo": total_no_intervalo,
            "intervalo": f"{horario} ±{intervalo}min"
        }
    except Exception as e:
        logging.error(f"Erro no filtro temporal: {e}")
        return {"scores": {}, "total_no_intervalo": 0}


def analisar_master(historico: List[int]) -> Dict:
    """Análise do padrão Master (exato)"""
    candidatos = {}
    janela = 3  # Janela de análise
    
    # Procurar padrões exatos nas últimas 100 rodadas
    for i in range(len(historico) - janela):
        padrao_atual = tuple(historico[i:i+janela])
        
        # Procurar esse padrão no histórico anterior
        for j in range(i + janela, min(len(historico) - 1, i + 200)):
            if tuple(historico[j:j+janela]) == padrao_atual:
                # Número que veio depois desse padrão
                proximo = historico[j + janela] if j + janela < len(historico) else None
                if proximo is not None:
                    candidatos[proximo] = candidatos.get(proximo, 0) + 1
    
    return {"scores": candidatos}


def analisar_estelar(historico: List[int]) -> Dict:
    """Análise do padrão Estelar (equivalências)"""
    candidatos = {}
    ultimo = historico[0]
    
    # Espelhos fixos
    ESPELHOS = {
        1:10, 10:1, 2:20, 20:2, 3:30, 30:3,
        6:9, 9:6, 16:19, 19:16, 26:29, 29:26,
        13:31, 31:13, 12:21, 21:12, 32:23, 23:32
    }
    
    # Roda europeia
    RODA = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]
    
    # 1. Espelhos (peso alto)
    if ultimo in ESPELHOS:
        candidatos[ESPELHOS[ultimo]] = candidatos.get(ESPELHOS[ultimo], 0) + 5
    
    # 2. Vizinhos (peso médio)
    idx = RODA.index(ultimo) if ultimo in RODA else -1
    if idx != -1:
        vizinho_esq = RODA[(idx - 1 + 37) % 37]
        vizinho_dir = RODA[(idx + 1) % 37]
        candidatos[vizinho_esq] = candidatos.get(vizinho_esq, 0) + 3
        candidatos[vizinho_dir] = candidatos.get(vizinho_dir, 0) + 3
    
    # 3. Terminal (peso baixo)
    terminal = ultimo % 10
    for i in range(37):
        if i % 10 == terminal and i != ultimo:
            candidatos[i] = candidatos.get(i, 0) + 1
    
    # 4. Soma de dígitos
    soma_ultimo = (ultimo // 10) + (ultimo % 10)
    for i in range(1, 37):
        soma_i = (i // 10) + (i % 10)
        if soma_i == soma_ultimo and i != ultimo:
            candidatos[i] = candidatos.get(i, 0) + 2
    
    # 5. Repetições recentes (últimos 50)
    contagem = {}
    for num in historico[1:51]:
        contagem[num] = contagem.get(num, 0) + 1
    
    for num, freq in contagem.items():
        if freq >= 2:
            candidatos[num] = candidatos.get(num, 0) + freq
    
    return {"scores": candidatos}


def analisar_chain(historico: List[int]) -> Dict:
    """Análise do padrão Chain (cadeias comportamentais)"""
    candidatos = {}
    cadeias = {}
    
    # Detectar puxadas recorrentes (X puxa Y duas ou mais vezes)
    for i in range(len(historico) - 1):
        atual = historico[i]
        proximo = historico[i + 1]
        
        chave = f"{atual}->{proximo}"
        cadeias[chave] = cadeias.get(chave, 0) + 1
    
    # Filtrar cadeias que acontecem 2+ vezes
    cadeias_fortes = {k: v for k, v in cadeias.items() if v >= 2}
    
    # Analisar padrão das últimas 5 rodadas
    ultimos_5 = historico[:25]
    
    # Verificar se há cadeias ativas
    faltantes = []
    
    for i in range(len(ultimos_5) - 1):
        chave = f"{ultimos_5[i]}->{ultimos_5[i+1]}"
        if chave in cadeias_fortes:
            # Procurar o que vem depois dessa cadeia
            for j in range(len(historico) - 2):
                if historico[j] == ultimos_5[i] and historico[j+1] == ultimos_5[i+1]:
                    if j + 2 < len(historico):
                        proximo = historico[j + 2]
                        candidatos[proximo] = candidatos.get(proximo, 0) + cadeias_fortes[chave]
                        faltantes.append(proximo)
    
    # Análise de faltantes comportamentais
    # Ex: 27-11-36 (vizinhos do 13) → falta 13
    RODA = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]
    
    for num in range(37):
        if num in RODA:
            idx = RODA.index(num)
            viz_esq = RODA[(idx - 1 + 37) % 37]
            viz_dir = RODA[(idx + 1) % 37]
            
            # Verificar se os vizinhos apareceram recentemente mas o número não
            if viz_esq in ultimos_5 and viz_dir in ultimos_5 and num not in ultimos_5[:10]:
                candidatos[num] = candidatos.get(num, 0) + 4
                faltantes.append(num)
    
    return {
        "scores": candidatos,
        "cadeias_detectadas": len(cadeias_fortes),
        "faltantes": list(set(faltantes))[:5]
    }


# =============================================
# FUNÇÕES AUXILIARES - NORMALIZAÇÃO E PESOS
# =============================================

def normalizar_scores(result: Dict) -> Dict[int, float]:
    """Normaliza scores para escala 0-100"""
    scores = result.get("scores", {})
    
    if not scores:
        return {}
    
    max_score = max(scores.values())
    if max_score == 0:
        return {}
    
    return {num: (score / max_score) * 100 for num, score in scores.items()}


def obter_pesos_por_modo(modo: str) -> Dict[str, float]:
    """Define pesos de cada filtro conforme o modo escolhido"""
    modos = {
        "equilibrado": {
            "puxadas": 0.20,
            "temporal": 0.20,
            "master": 0.20,
            "estelar": 0.20,
            "chain": 0.20
        },
        "conservador": {
            "puxadas": 0.35,
            "temporal": 0.35,
            "master": 0.10,
            "estelar": 0.10,
            "chain": 0.10
        },
        "agressivo": {
            "puxadas": 0.10,
            "temporal": 0.10,
            "master": 0.25,
            "estelar": 0.25,
            "chain": 0.30
        },
        "temporal": {
            "puxadas": 0.15,
            "temporal": 0.50,
            "master": 0.10,
            "estelar": 0.15,
            "chain": 0.10
        },
        "chain": {
            "puxadas": 0.15,
            "temporal": 0.10,
            "master": 0.15,
            "estelar": 0.20,
            "chain": 0.40
        }
    }
    
    return modos.get(modo, modos["equilibrado"])


def calcular_confianca(detalhes: Dict) -> str:
    """Calcula nível de confiança baseado em quantos filtros concordam"""
    qtd_filtros = len(detalhes["filtros_ativos"])
    
    if qtd_filtros >= 4:
        return "muito_alta"
    elif qtd_filtros >= 3:
        return "alta"
    elif qtd_filtros >= 2:
        return "media"
    else:
        return "baixa"


def analisar_consenso(ranking: List, normalized: Dict) -> Dict:
    """Analisa consenso entre os filtros"""
    # Números que aparecem em múltiplos filtros
    consenso_forte = []  # 4+ filtros
    consenso_medio = []  # 3 filtros
    consenso_fraco = []  # 2 filtros
    
    for item in ranking:
        num = item["numero"]
        filtros = item["detalhes"]["filtros_ativos"]
        qtd = len(filtros)
        
        if qtd >= 4:
            consenso_forte.append(num)
        elif qtd >= 3:
            consenso_medio.append(num)
        elif qtd >= 2:
            consenso_fraco.append(num)
    
    return {
        "consenso_forte": consenso_forte[:5],
        "consenso_medio": consenso_medio[:5],
        "consenso_fraco": consenso_fraco[:5],
        "total_com_consenso": len(consenso_forte) + len(consenso_medio)
    }


def aplicar_protecoes(ranking: List, ultimo_numero: int) -> List[int]:
    """Adiciona proteções estratégicas"""
    ESPELHOS = {
        1:10, 10:1, 2:20, 20:2, 3:30, 30:3,
        6:9, 9:6, 16:19, 19:16, 26:29, 29:26,
        13:31, 31:13, 12:21, 21:12, 32:23, 23:32
    }
    
    sugestoes = [r["numero"] for r in ranking]
    protecoes = set(sugestoes)
    
    # Sempre incluir zero (se não estiver)
    protecoes.add(0)
    
    # Incluir espelho do último número
    if ultimo_numero in ESPELHOS:
        protecoes.add(ESPELHOS[ultimo_numero])
    
    # Incluir espelhos das top 3 sugestões
    for num in sugestoes[:3]:
        if num in ESPELHOS:
            protecoes.add(ESPELHOS[num])
    
    return sorted(list(protecoes))[:18]  # Máximo 18 números


def gerar_insights(ranking: List, consenso: Dict, puxadas: Dict, temporal: Dict, chain: Dict) -> List[str]:
    """Gera insights automáticos"""
    insights = []
    
    if ranking:
        top1 = ranking[0]
        insights.append(
            f"🎯 Número mais provável: {top1['numero']} "
            f"(score {top1['score']}, confiança {top1['confianca']})"
        )
        
        qtd_filtros = len(top1['detalhes']['filtros_ativos'])
        if qtd_filtros >= 4:
            insights.append(
                f"⭐ {top1['numero']} tem consenso de {qtd_filtros}/5 filtros!"
            )
    
    if consenso.get("consenso_forte"):
        nums = ", ".join(str(n) for n in consenso["consenso_forte"][:3])
        insights.append(f"🔥 Consenso forte (4+ filtros): {nums}")
    
    if puxadas.get("confianca") == "alta":
        insights.append("✅ Filtro de puxadas tem alta confiança (100+ ocorrências)")
    
    if temporal.get("total_no_intervalo", 0) > 50:
        insights.append(
            f"⏰ Filtro temporal forte: {temporal['total_no_intervalo']} ocorrências no horário"
        )
    
    if chain.get("faltantes"):
        faltantes = ", ".join(str(n) for n in chain["faltantes"][:3])
        insights.append(f"⛓️ Faltantes detectados pela Chain: {faltantes}")
    
    return insights


 

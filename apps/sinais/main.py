"""App FastAPI do produto de sinais (sinais.revesbot.com.br)."""

import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from sinais.core.db import ensure_indexes
from sinais.routes.billing import router as billing_router
from sinais.routes.entries import router as entries_router
from sinais.routes.pages import router as pages_router
from sinais.routes.webhooks import router as webhooks_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

app = FastAPI(title="Revesbot Sinais")

# Auth é por Bearer token (não cookies cross-site), então liberar origem é seguro.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(pages_router)
app.include_router(entries_router)
app.include_router(billing_router)
app.include_router(webhooks_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


async def _ensure_indexes_bg():
    try:
        await ensure_indexes()
    except Exception as exc:  # Mongo indisponível não deve derrubar/atrasar o boot
        logging.warning("ensure_indexes falhou: %s", exc)


@app.on_event("startup")
async def _startup():
    # Não bloqueia o boot esperando o Mongo (ex.: túnel SSH fora do ar em dev).
    asyncio.create_task(_ensure_indexes_bg())

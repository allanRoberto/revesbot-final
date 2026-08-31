from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.routes.pixgo_webhook import router as pixgo_webhook_router
from api.routes.results_websocket import router as results_websocket_router
from api.routes.roulette_analyzer import router as roulette_analyzer_router
from api.routes.roulette_history import router as roulette_history_router


BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="Revesbot Results API",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.middleware("http")
async def request_timing(request: Request, call_next):
    started_at = time.perf_counter()
    try:
        return await call_next(request)
    finally:
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        if elapsed_ms >= 1000:
            logging.warning(
                "slow_request method=%s path=%s elapsed_ms=%.2f pid=%s",
                request.method,
                request.url.path,
                elapsed_ms,
                os.getpid(),
            )


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(roulette_history_router)
app.include_router(roulette_analyzer_router)
app.include_router(results_websocket_router)
app.include_router(pixgo_webhook_router)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

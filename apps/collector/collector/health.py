from __future__ import annotations

import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .config import CollectorSettings
from .metrics import render_metrics
from .state import CollectorState


def start_health_server(state: CollectorState, settings: CollectorSettings) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/health/live":
                self._json(200, {"status": "live"})
                return
            ready, _ = state.readiness(
                settings.ws_stale_seconds,
                settings.result_stale_seconds,
                settings.startup_grace_seconds,
            )
            if self.path == "/health/ready":
                self._json(
                    200 if ready else 503,
                    state.snapshot(
                        settings.ws_stale_seconds,
                        settings.result_stale_seconds,
                        settings.startup_grace_seconds,
                    ),
                )
                return
            if self.path == "/metrics":
                payload = render_metrics(state, ready).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            self._json(404, {"detail": "not found"})

        def _json(self, status: int, body: dict) -> None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args) -> None:
            return

    server = ThreadingHTTPServer((settings.health_host, settings.health_port), Handler)
    threading.Thread(target=server.serve_forever, name="collector-health", daemon=True).start()
    return server


def start_watchdog(state: CollectorState, settings: CollectorSettings) -> threading.Thread:
    logger = logging.getLogger("collector.watchdog")

    def run() -> None:
        consecutive_failures = 0
        while not stop.wait(settings.watchdog_interval_seconds):
            ready, reasons = state.readiness(
                settings.ws_stale_seconds,
                settings.result_stale_seconds,
                settings.startup_grace_seconds,
            )
            if ready:
                consecutive_failures = 0
                continue
            # A normal reconnect is handled by the provider loop. Staleness
            # or dependency failures require a full process restart.
            actionable = [reason for reason in reasons if reason != "websocket_disconnected"]
            if not actionable:
                continue
            consecutive_failures += 1
            with state._lock:
                state.watchdog_failures_total += 1
            logger.error(
                "watchdog_unhealthy reasons=%s consecutive_failures=%s",
                ",".join(reasons),
                consecutive_failures,
            )
            if settings.watchdog_exit_enabled and consecutive_failures >= settings.watchdog_failures_before_exit:
                logger.critical("watchdog_exiting_for_supervisor_restart")
                os._exit(70)

    stop = threading.Event()
    thread = threading.Thread(target=run, name="collector-watchdog", daemon=True)
    thread.start()
    return thread

from __future__ import annotations

from .state import CollectorState


def render_metrics(state: CollectorState, ready: bool) -> str:
    snapshot = state.snapshot(10**9, 10**9, 10**9)
    values = {
        "revesbot_collector_ready": int(ready),
        "revesbot_collector_websocket_connected": int(snapshot["websocket_connected"]),
        "revesbot_collector_mongo_ok": int(snapshot["mongo_ok"]),
        "revesbot_collector_redis_ok": int(snapshot["redis_ok"]),
        "revesbot_collector_results_total": snapshot["results_total"],
        "revesbot_collector_duplicates_total": snapshot["duplicates_total"],
        "revesbot_collector_reconnects_total": snapshot["reconnects_total"],
        "revesbot_collector_mongo_errors_total": snapshot["mongo_errors_total"],
        "revesbot_collector_redis_errors_total": snapshot["redis_errors_total"],
        "revesbot_collector_invalid_messages_total": snapshot["invalid_messages_total"],
        "revesbot_collector_watchdog_failures_total": snapshot["watchdog_failures_total"],
        "revesbot_collector_recovered_results_total": snapshot["recovered_results_total"],
        "revesbot_collector_recovery_failures_total": snapshot["recovery_failures_total"],
        "revesbot_collector_tables_seen": snapshot["tables_seen"],
    }
    return "\n".join(f"{name} {value}" for name, value in values.items()) + "\n"

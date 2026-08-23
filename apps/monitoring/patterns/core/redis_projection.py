from __future__ import annotations

import json
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping


log = logging.getLogger("patterns.redis-projection")


def json_default(value: Any):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


class RedisProjection:
    """Projecao best-effort; nunca participa da apuracao do pattern."""

    def __init__(self, client=None, *, ttl_seconds: int = 180):
        self.client = client
        self.ttl_seconds = ttl_seconds

    def publish_dashboard(self, pattern_key: str, snapshot: Mapping[str, Any]) -> bool:
        if self.client is None:
            return False
        payload = json.dumps(dict(snapshot), default=json_default, ensure_ascii=False)
        try:
            pipeline = self.client.pipeline(transaction=False)
            pipeline.setex(
                f"patterns:{pattern_key}:dashboard",
                self.ttl_seconds,
                payload,
            )
            pipeline.publish(
                "patterns:updates",
                json.dumps(
                    {"pattern_key": pattern_key, "type": "dashboard"},
                    ensure_ascii=False,
                ),
            )
            pipeline.execute()
            return True
        except Exception as exc:  # Redis jamais interrompe o monitoramento
            log.warning("Projecao Redis indisponivel para %s: %s", pattern_key, exc)
            return False

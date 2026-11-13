"""HTTP client for the internal vector search service (``apps/vector_search``)."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable, Sequence

import httpx

ROULETTE_ID = "pragmatic-brazilian-roulette"

# Same body sent by apps/api/static/js/pages/contextual-similarity.js. The worker
# adds ``cutoff`` (the triggering result time) so a search never sees later data.
PAGE_SEARCH_PARAMETERS: dict[str, Any] = {
    "roulette_id": ROULETTE_ID,
    "mode": "vector",
    "exact": False,
    "radius": 1,
    "enable_digit_sum": False,
    "enable_inverse": True,
    "enable_custom_inverse": True,
    "enable_terminal": False,
    "strict_order": True,
    "min_similarity": 0.85,
    "k": 100,
    "limit": 100,
}
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class SearchError(RuntimeError):
    """The vector search could not return occurrences."""


def _numbers(values: Any) -> Any:
    if not isinstance(values, list):
        return None
    return [int(value) if isinstance(value, float) and value.is_integer() else value for value in values]


def compact_occurrence(raw: Any) -> dict[str, Any]:
    """Keep only the fields the page rules read, preserving invalid values as invalid."""
    raw = raw if isinstance(raw, dict) else {}
    similarity = raw.get("similarity")
    return {
        "id": raw["id"] if isinstance(raw.get("id"), str) else "",
        "context": _numbers(raw.get("context")),
        "following": _numbers(raw.get("following")),
        "preceding": _numbers(raw.get("preceding")),
        "preceding_complete": raw.get("preceding_complete") is True,
        "preceding_lookup_status": str(raw.get("preceding_lookup_status") or "unavailable"),
        "similarity": float(similarity) if isinstance(similarity, (int, float))
        and not isinstance(similarity, bool) else None,
        "context_end_at": raw.get("context_end_at") if isinstance(raw.get("context_end_at"), str) else None,
    }


class VectorSearchClient:
    def __init__(self, base_url: str, token: str, *, timeout: float = 15.0,
                 backoff_seconds: float = 1.0, client: httpx.Client | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.base_url = base_url.rstrip("/")
        self.token = (token or "").strip()
        self.backoff_seconds = backoff_seconds
        self._client = client or httpx.Client(timeout=timeout)
        self._sleep = sleep

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def close(self) -> None:
        self._client.close()

    def search(self, sequence: Sequence[int], cutoff: datetime, attempts: int = 3) -> dict[str, Any]:
        if not self.configured:
            raise SearchError("VECTOR_API_TOKEN não configurado.")
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=timezone.utc)
        payload = {"sequence": list(sequence), **PAGE_SEARCH_PARAMETERS, "cutoff": cutoff.isoformat()}
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        last_error = "falha desconhecida"
        for attempt in range(max(1, attempts)):
            if attempt:
                self._sleep(self.backoff_seconds * attempt)
            try:
                response = self._client.post(f"{self.base_url}/search", json=payload, headers=headers)
            except httpx.HTTPError as error:
                last_error = f"{type(error).__name__} ao consultar a busca vetorial"
                continue
            if response.status_code in RETRYABLE_STATUS:
                last_error = f"busca vetorial respondeu HTTP {response.status_code}"
                continue
            if response.status_code != 200:
                raise SearchError(f"busca vetorial recusou a consulta (HTTP {response.status_code})")
            try:
                body = response.json()
            except ValueError:
                last_error = "busca vetorial devolveu uma resposta inválida"
                continue
            occurrences = body.get("occurrences") if isinstance(body, dict) else None
            if not isinstance(occurrences, list):
                raise SearchError("busca vetorial devolveu uma resposta sem ocorrências")
            total = body.get("total_matches")
            return {
                "occurrences": [compact_occurrence(item) for item in occurrences],
                "total_matches": total if isinstance(total, int) and not isinstance(total, bool)
                else len(occurrences),
            }
        raise SearchError(last_error)

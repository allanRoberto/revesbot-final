"""In-memory doubles for Redis, the results history, the search and MongoDB."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from contextual_ranking.engine import spin

START = datetime(2026, 11, 13, 15, 0, tzinfo=timezone.utc)


def make_spins(numbers: list[int], first: int = 1) -> list[dict[str, Any]]:
    return [spin(f"h{first + index:04d}", number, START + timedelta(seconds=40 * (first + index)))
            for index, number in enumerate(numbers)]


class MemoryPipeline:
    def __init__(self, redis):
        self.redis = redis
        self.operations = []

    def __getattr__(self, name):
        def queue(*args):
            self.operations.append((name, args))
            return self
        return queue

    def execute(self):
        if self.redis.fail_next_execute:
            self.redis.fail_next_execute = False
            raise ConnectionError("redis caiu")
        for name, args in self.operations:
            getattr(self.redis, name)(*args)


class MemoryRedis:
    def __init__(self):
        self.values: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}
        self.hashes: dict[str, dict[str, int]] = {}
        self.fail_next_execute = False

    def pipeline(self, transaction=True):
        assert transaction is True
        return MemoryPipeline(self)

    def get(self, key): return self.values.get(key)
    def set(self, key, value): self.values[key] = value
    def lpush(self, key, value): self.lists.setdefault(key, []).insert(0, value)
    def ltrim(self, key, start, end): self.lists[key] = self.lists.get(key, [])[start:end + 1]
    def llen(self, key): return len(self.lists.get(key, []))
    def lrange(self, key, start, end): return self.lists.get(key, [])[start:end + 1]

    def lindex(self, key, index):
        values = self.lists.get(key, [])
        return values[index] if values else None

    def rpop(self, key):
        values = self.lists.get(key, [])
        return values.pop() if values else None

    def hincrby(self, key, field, amount):
        bucket = self.hashes.setdefault(key, {})
        bucket[field] = bucket.get(field, 0) + amount

    def hgetall(self, key): return {name: str(value) for name, value in self.hashes.get(key, {}).items()}


class MemoryHistory:
    def __init__(self, spins: list[dict[str, Any]] | None = None):
        self.spins = list(spins or [])

    def latest(self, limit):
        return self.spins[-limit:]

    def after(self, cursor, limit):
        ids = [item["history_id"] for item in self.spins]
        position = ids.index(cursor["history_id"]) + 1 if cursor["history_id"] in ids else 0
        return self.spins[position:position + limit]


class FakeSearch:
    """Returns the same table for every sequence unless told otherwise."""

    def __init__(self, occurrences: list[dict[str, Any]] | None = None):
        self.occurrences = occurrences if occurrences is not None else default_occurrences()
        self.calls: list[tuple[list[int], datetime, int]] = []
        self.failing: set[tuple[int, ...]] = set()

    def __call__(self, sequence, cutoff, attempts):
        self.calls.append((list(sequence), cutoff, attempts))
        if tuple(sequence) in self.failing:
            raise RuntimeError("busca vetorial indisponível")
        return {"occurrences": [dict(row) for row in self.occurrences], "total_matches": len(self.occurrences)}


def default_occurrences() -> list[dict[str, Any]]:
    rows = [
        ([1, 2, 3, 4, 5], [10, 11, 12, 13], [0, 0, 0, 0, 0]),
        ([6, 7, 8, 9, 10], [14, 15, 16, 17], [5, 5, 5, 5, 5]),
        ([11, 12, 13, 14, 15], [18, 19, 20, 21], [17, 17, 17, 17, 17]),
        ([16, 17, 18, 19, 20], [22, 23, 24, 25], [33, 33, 33, 33, 33]),
        ([21, 22, 23, 24, 25], [26, 27, 28, 29], [36, 36, 36, 36, 36]),
    ]
    return [{"id": f"o{index}", "preceding": preceding, "preceding_complete": True,
             "preceding_lookup_status": "complete", "context": context, "following": following}
            for index, (preceding, context, following) in enumerate(rows)]


class FakeWriter:
    def __init__(self):
        self.documents: dict[str, dict[str, Any]] = {}
        self.failing = False

    def write(self, signal):
        if self.failing:
            raise TimeoutError("mongo fora do ar")
        from contextual_ranking.storage import to_mongo_document
        document = to_mongo_document(signal)
        self.documents[document["_id"]] = document

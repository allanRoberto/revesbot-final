from monitoring.scripts.triple_context_live_worker import (
    HISTORY_KEY, STATE_KEY, SUMMARY_KEY, TripleContextLiveWorker, decode, next_phase,
)


class MemoryPipeline:
    def __init__(self, redis):
        self.redis = redis
        self.operations = []

    def lpush(self, *args): self.operations.append(("lpush", args)); return self
    def ltrim(self, *args): self.operations.append(("ltrim", args)); return self
    def hincrby(self, *args): self.operations.append(("hincrby", args)); return self
    def set(self, *args): self.operations.append(("set", args)); return self

    def execute(self):
        for name, args in self.operations:
            getattr(self.redis, name)(*args)


class MemoryRedis:
    def __init__(self):
        self.values = {}
        self.lists = {}
        self.hashes = {}

    def pipeline(self, *, transaction):
        assert transaction is True
        return MemoryPipeline(self)

    def set(self, key, value): self.values[key] = value
    def lpush(self, key, value): self.lists.setdefault(key, []).insert(0, value)
    def ltrim(self, key, start, end): self.lists[key] = self.lists.get(key, [])[start:end + 1]
    def hincrby(self, key, field, amount): self.hashes.setdefault(key, {})[field] = self.hashes.setdefault(key, {}).get(field, 0) + amount


def test_collects_exactly_three_results_before_waiting_for_attempt():
    first = {"number": 7}
    second = {"number": 5}
    third = {"number": 23}
    phase, buffer = next_phase("collecting", [], first)
    assert (phase, buffer) == ("collecting", [first])
    phase, buffer = next_phase(phase, buffer, second)
    assert (phase, buffer) == ("collecting", [first, second])
    phase, buffer = next_phase(phase, buffer, third)
    assert (phase, buffer) == ("awaiting_result", [first, second, third])


def test_attempt_result_starts_a_fresh_non_overlapping_block():
    phase, buffer = next_phase("awaiting_result", [{"number": 7}, {"number": 5}, {"number": 23}], {"number": 12})
    assert phase == "collecting"
    assert buffer == []


def test_records_top_six_and_settles_exactly_one_attempt():
    worker = object.__new__(TripleContextLiveWorker)
    worker.catalog_ranking = lambda trio: {
        "build_id": "build-1", "key": ",".join(map(str, trio)),
        "occurrences": 9, "context_events": 30,
        "top": [
            {"position": position, "number": number, "score": 7 - position, "direct_hits": position}
            for position, number in enumerate([12, 21, 3, 30, 9, 18], 1)
        ],
    }
    spins = [
        {"history_id": "a", "number": 7, "timestamp": "t1"},
        {"history_id": "b", "number": 5, "timestamp": "t2"},
        {"history_id": "c", "number": 23, "timestamp": "t3"},
    ]
    entry = worker.build_signal(spins)
    assert entry["trio"] == [7, 5, 23]
    assert entry["top_numbers"] == [12, 21, 3, 30, 9, 18]
    assert entry["configuration"]["attempts"] == 1

    outcome = worker.settle(entry, {"history_id": "d", "number": 21, "timestamp": "t4"})
    assert outcome["status"] == "won"
    assert outcome["result"]["hit"] is True
    assert outcome["result"]["number"] == 21


def test_settlement_persists_history_summary_and_cursor_atomically():
    worker = object.__new__(TripleContextLiveWorker)
    worker.redis = MemoryRedis()
    pending = {
        "id": "c", "status": "pending", "trio": [7, 5, 23],
        "top_numbers": [12, 21, 3, 30, 9, 18], "ranking": [],
        "created_at": "t3", "result": None,
    }
    state = {"phase": "awaiting_result", "buffer": [], "pending_signal": pending}
    result = {"_id": "d", "value": 8, "timestamp": "t4"}

    next_state = worker.process(state, result)

    assert next_state["phase"] == "collecting"
    assert next_state["pending_signal"] is None
    assert decode(worker.redis.lists[HISTORY_KEY][0])["status"] == "lost"
    assert worker.redis.hashes[SUMMARY_KEY]["lost"] == 1
    assert decode(worker.redis.values[STATE_KEY])["last_processed"]["history_id"] == "d"

from types import SimpleNamespace

from monitoring.scripts.triple_context_live_worker import TripleContextLiveWorker, next_phase


class MemorySignals:
    def __init__(self):
        self.document = None

    def insert_one(self, document):
        self.document = {"_id": "signal-1", **document}
        return SimpleNamespace(inserted_id="signal-1")

    def find_one(self, query):
        if self.document and all(self.document.get(key) == value for key, value in query.items()):
            return self.document
        return None

    def update_one(self, query, update):
        if self.find_one(query):
            self.document.update(update["$set"])


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
    worker.signals = MemorySignals()
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
    signal_id = worker.record_signal(spins)
    assert signal_id == "signal-1"
    assert worker.signals.document["trio"] == [7, 5, 23]
    assert worker.signals.document["top_numbers"] == [12, 21, 3, 30, 9, 18]
    assert worker.signals.document["configuration"]["attempts"] == 1

    worker.settle("signal-1", {"history_id": "d", "number": 21, "timestamp": "t4"})
    assert worker.signals.document["status"] == "won"
    assert worker.signals.document["result"]["hit"] is True
    assert worker.signals.document["result"]["number"] == 21

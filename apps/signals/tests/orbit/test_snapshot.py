from datetime import datetime, timezone

from apps.signals.orbit_engine.snapshot import _serialize_record


def test_naive_bson_datetime_is_interpreted_as_utc():
    row = _serialize_record(
        {
            "_id": "abc",
            "roulette_id": "test",
            "value": 19,
            "timestamp": datetime(2026, 7, 20, 17, 0, 0),
        }
    )
    assert row["timestamp"] == "2026-07-20T17:00:00+00:00"


def test_aware_datetime_is_normalized_to_utc():
    row = _serialize_record(
        {
            "_id": "abc",
            "roulette_id": "test",
            "value": 19,
            "timestamp": datetime(2026, 7, 20, 17, 0, 0, tzinfo=timezone.utc),
        }
    )
    assert row["timestamp"] == "2026-07-20T17:00:00+00:00"

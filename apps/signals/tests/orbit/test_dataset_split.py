from datetime import datetime, timedelta, timezone

from apps.signals.orbit_engine.dataset import iter_replay_decisions
from apps.signals.orbit_engine.snapshot import SpinRecord
from shared.python.roulette.orbit.orbit_builder import OrbitBuilder


def _records(total: int = 500):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return tuple(
        SpinRecord(
            roulette_id="test",
            value=index % 37,
            timestamp=start + timedelta(seconds=index),
            source_id=str(index),
        )
        for index in range(total)
    )


def test_replay_respects_exclusive_temporal_anchor_range():
    decisions = tuple(
        iter_replay_decisions(
            _records(),
            builder=OrbitBuilder(memory_occurrences=4),
            horizon=3,
            warmup=50,
            anchor_start=200,
            anchor_end=210,
        )
    )
    assert [row.context.anchor_index for row in decisions] == list(range(200, 210))
    assert all(len(row.targets) == 3 for row in decisions)


def test_training_boundary_can_keep_all_targets_inside_train_block():
    train_end = 300
    horizon = 3
    decisions = tuple(
        iter_replay_decisions(
            _records(),
            builder=OrbitBuilder(memory_occurrences=4),
            horizon=horizon,
            warmup=50,
            anchor_start=50,
            anchor_end=train_end - horizon,
        )
    )
    assert decisions[-1].context.anchor_index + horizon < train_end

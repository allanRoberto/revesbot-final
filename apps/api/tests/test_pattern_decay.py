"""Tests for Pattern Decay Module."""
import json
import tempfile
from pathlib import Path

import pytest

from api.services.pattern_decay import (
    DecayConfig,
    PatternDecayState,
    PatternDecayManager,
)


class TestDecayConfig:
    """Tests for DecayConfig dataclass."""

    def test_defaults(self):
        config = DecayConfig()
        assert config.decay_start_misses == 3
        assert config.decay_per_miss == 0.10
        assert config.max_decay == 0.50
        assert config.disable_threshold == 8
        assert config.recovery_hits_needed == 3
        assert config.recovery_per_hit == 0.15

    def test_to_dict(self):
        config = DecayConfig()
        d = config.to_dict()
        assert d["decay_start_misses"] == 3
        assert d["max_decay"] == 0.50

    def test_from_dict(self):
        data = {
            "decay_start_misses": 5,
            "decay_per_miss": 0.15,
            "max_decay": 0.40,
            "disable_threshold": 10,
            "recovery_hits_needed": 4,
            "recovery_per_hit": 0.20,
        }
        config = DecayConfig.from_dict(data)
        assert config.decay_start_misses == 5
        assert config.decay_per_miss == 0.15


class TestPatternDecayState:
    """Tests for PatternDecayState dataclass."""

    def test_multiplier_no_decay(self):
        state = PatternDecayState(pattern_id="test", current_decay=0.0)
        assert state.multiplier == 1.0

    def test_multiplier_with_decay(self):
        state = PatternDecayState(pattern_id="test", current_decay=0.3)
        assert state.multiplier == 0.7

    def test_multiplier_max_decay(self):
        state = PatternDecayState(pattern_id="test", current_decay=0.5)
        assert state.multiplier == 0.5

    def test_multiplier_disabled(self):
        state = PatternDecayState(pattern_id="test", is_disabled=True)
        assert state.multiplier == 0.0

    def test_hit_rate(self):
        state = PatternDecayState(
            pattern_id="test",
            total_signals=10,
            total_hits=7,
        )
        assert state.hit_rate == 0.7

    def test_hit_rate_no_signals(self):
        state = PatternDecayState(pattern_id="test")
        assert state.hit_rate == 0.5  # Default

    def test_to_dict(self):
        state = PatternDecayState(
            pattern_id="test",
            consecutive_misses=3,
            current_decay=0.2,
        )
        d = state.to_dict()
        assert d["pattern_id"] == "test"
        assert d["consecutive_misses"] == 3
        assert d["multiplier"] == 0.8


class TestPatternDecayManager:
    """Tests for PatternDecayManager."""

    @pytest.fixture
    def temp_storage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "test_decay.json"

    @pytest.fixture
    def manager(self, temp_storage):
        return PatternDecayManager(storage_path=temp_storage)

    def test_record_hit(self, manager):
        """Hit should reset miss streak and potentially recover decay."""
        state = manager.record_result("pattern_1", hit=True)
        assert state.consecutive_hits == 1
        assert state.consecutive_misses == 0
        assert state.total_hits == 1

    def test_record_miss(self, manager):
        """Miss should increment miss streak."""
        state = manager.record_result("pattern_1", hit=False)
        assert state.consecutive_misses == 1
        assert state.consecutive_hits == 0
        assert state.total_misses == 1

    def test_decay_applied_after_threshold(self, manager):
        """Decay should apply after decay_start_misses consecutive misses."""
        # Miss 3 times (default decay_start_misses)
        for _ in range(3):
            state = manager.record_result("pattern_1", hit=False)

        assert state.consecutive_misses == 3
        assert state.current_decay > 0

    def test_pattern_disabled_after_threshold(self, manager):
        """Pattern should be disabled after disable_threshold misses."""
        # Miss 8 times (default disable_threshold)
        for _ in range(8):
            state = manager.record_result("pattern_1", hit=False)

        assert state.is_disabled is True
        assert manager.is_disabled("pattern_1") is True

    def test_recovery_after_hits(self, manager):
        """Decay should recover after enough hits."""
        # First apply some decay
        for _ in range(5):
            manager.record_result("pattern_1", hit=False)

        initial_decay = manager._states["pattern_1"].current_decay
        assert initial_decay > 0

        # Now hit 3 times (default recovery_hits_needed)
        for _ in range(3):
            state = manager.record_result("pattern_1", hit=True)

        assert state.current_decay < initial_decay

    def test_get_multiplier_unknown_pattern(self, manager):
        """Unknown pattern should return 1.0."""
        mult = manager.get_multiplier("unknown_pattern")
        assert mult == 1.0

    def test_get_multiplier_with_decay(self, manager):
        """Should return correct multiplier based on decay."""
        for _ in range(5):
            manager.record_result("pattern_1", hit=False)

        mult = manager.get_multiplier("pattern_1")
        assert mult < 1.0

    def test_reset_pattern(self, manager):
        """Reset should clear pattern state."""
        for _ in range(5):
            manager.record_result("pattern_1", hit=False)

        result = manager.reset_pattern("pattern_1")
        assert result["reset"] is True

        state = manager._states["pattern_1"]
        assert state.consecutive_misses == 0
        assert state.current_decay == 0.0

    def test_reset_pattern_not_found(self, manager):
        """Reset should return error for unknown pattern."""
        result = manager.reset_pattern("unknown")
        assert result["reset"] is False

    def test_reset_all(self, manager):
        """Reset all should clear all states."""
        manager.record_result("p1", hit=False)
        manager.record_result("p2", hit=False)

        result = manager.reset_all()
        assert result["reset"] is True
        assert len(manager._states) == 0

    def test_configure(self, manager):
        """Configure should update settings."""
        result = manager.configure(
            decay_start_misses=5,
            max_decay=0.7,
        )
        assert result["updated"] is True
        assert result["config"]["decay_start_misses"] == 5
        assert result["config"]["max_decay"] == 0.7

    def test_get_decay_report(self, manager):
        """Report should include all pattern states."""
        manager.record_result("p1", hit=True)
        manager.record_result("p2", hit=False)
        for _ in range(8):
            manager.record_result("p3", hit=False)

        report = manager.get_decay_report()
        assert report["summary"]["total_patterns"] == 3
        assert report["summary"]["disabled_patterns"] == 1
        assert "patterns" in report

    def test_get_disabled_patterns(self, manager):
        """Should return list of disabled pattern IDs."""
        for _ in range(8):
            manager.record_result("p1", hit=False)
        manager.record_result("p2", hit=True)

        disabled = manager.get_disabled_patterns()
        assert "p1" in disabled
        assert "p2" not in disabled

    def test_batch_result(self, manager):
        """Should update multiple patterns at once."""
        results = manager.record_batch_result(["p1", "p2", "p3"], hit=True)
        assert len(results) == 3
        assert all(s.total_hits == 1 for s in results.values())

    def test_save_and_load(self, temp_storage):
        """State should persist to disk."""
        manager1 = PatternDecayManager(storage_path=temp_storage)
        for _ in range(4):
            manager1.record_result("pattern_1", hit=False)
        manager1.save()

        manager2 = PatternDecayManager(storage_path=temp_storage)
        state = manager2._states.get("pattern_1")
        assert state is not None
        assert state.consecutive_misses == 4


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

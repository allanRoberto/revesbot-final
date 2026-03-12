"""Tests for Suggestion Filter Module."""
import json
import tempfile
from pathlib import Path

import pytest

from api.services.suggestion_filter import (
    FilterResult,
    SuggestionFilter,
)


class TestFilterResult:
    """Tests for FilterResult dataclass."""

    def test_to_dict_passed(self):
        result = FilterResult(
            passed=True,
            reason=None,
            filter_details={"min_patterns": {"passed": True, "threshold": 3, "actual": 5}},
        )
        d = result.to_dict()
        assert d["passed"] is True
        assert d["reason"] is None
        assert "min_patterns" in d["filter_details"]

    def test_to_dict_failed(self):
        result = FilterResult(
            passed=False,
            reason="Padroes insuficientes: 2/3",
            filter_details={"min_patterns": {"passed": False, "threshold": 3, "actual": 2}},
        )
        d = result.to_dict()
        assert d["passed"] is False
        assert "Padroes insuficientes" in d["reason"]


class TestSuggestionFilter:
    """Tests for SuggestionFilter."""

    @pytest.fixture
    def temp_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "test_filters.json"

    @pytest.fixture
    def filter_instance(self, temp_config):
        return SuggestionFilter(config_path=temp_config)

    def test_default_filters_loaded(self, filter_instance):
        """Default filters should be available."""
        config = filter_instance.get_filter_config()
        filters = config["filters"]
        assert "min_patterns" in filters
        assert "min_confidence" in filters
        assert "max_negative_pressure" in filters
        assert "min_overlap_ratio" in filters

    def test_should_suggest_all_pass(self, filter_instance):
        """Should pass when all criteria are met."""
        contributions = [
            {"pattern_id": "p1", "numbers": [1, 2], "weight": 1.0},
            {"pattern_id": "p2", "numbers": [2, 3], "weight": 1.0},
            {"pattern_id": "p3", "numbers": [3, 4], "weight": 1.0},
            {"pattern_id": "p4", "numbers": [4, 5], "weight": 1.0},
        ]
        context = {
            "negative_pressure": 0.2,
            "consensus_score": 0.5,
            "weighted_consensus": 0.5,
        }
        confidence_score = 70

        result = filter_instance.should_suggest(contributions, context, confidence_score)
        assert result.passed is True
        assert result.reason is None

    def test_should_suggest_min_patterns_fail(self, filter_instance):
        """Should fail when not enough patterns."""
        contributions = [
            {"pattern_id": "p1", "numbers": [1, 2], "weight": 1.0},
            {"pattern_id": "p2", "numbers": [2, 3], "weight": 1.0},
        ]
        context = {
            "negative_pressure": 0.2,
            "consensus_score": 0.5,
            "weighted_consensus": 0.5,
        }
        confidence_score = 70

        result = filter_instance.should_suggest(contributions, context, confidence_score)
        assert result.passed is False
        assert "Padroes insuficientes" in result.reason

    def test_should_suggest_min_confidence_fail(self, filter_instance):
        """Should fail when confidence is too low."""
        contributions = [
            {"pattern_id": f"p{i}", "numbers": [i], "weight": 1.0}
            for i in range(5)
        ]
        context = {
            "negative_pressure": 0.2,
            "consensus_score": 0.5,
            "weighted_consensus": 0.5,
        }
        confidence_score = 40  # Below 55 threshold

        result = filter_instance.should_suggest(contributions, context, confidence_score)
        assert result.passed is False
        assert "Confianca baixa" in result.reason

    def test_should_suggest_negative_pressure_fail(self, filter_instance):
        """Should fail when negative pressure is too high."""
        contributions = [
            {"pattern_id": f"p{i}", "numbers": [i], "weight": 1.0}
            for i in range(5)
        ]
        context = {
            "negative_pressure": 0.6,  # Above 0.45 threshold
            "consensus_score": 0.5,
            "weighted_consensus": 0.5,
        }
        confidence_score = 70

        result = filter_instance.should_suggest(contributions, context, confidence_score)
        assert result.passed is False
        assert "Pressao negativa" in result.reason

    def test_should_suggest_overlap_fail(self, filter_instance):
        """Should fail when consensus is too low."""
        contributions = [
            {"pattern_id": f"p{i}", "numbers": [i], "weight": 1.0}
            for i in range(5)
        ]
        context = {
            "negative_pressure": 0.2,
            "consensus_score": 0.1,
            "weighted_consensus": 0.1,  # Below 0.25 threshold
        }
        confidence_score = 70

        result = filter_instance.should_suggest(contributions, context, confidence_score)
        assert result.passed is False
        assert "Consenso baixo" in result.reason

    def test_update_filter(self, filter_instance):
        """Should update filter configuration."""
        result = filter_instance.update_filter(
            filter_name="min_confidence",
            enabled=False,
            threshold=80,
        )
        assert result["updated"] is True
        assert result["config"]["enabled"] is False
        assert result["config"]["threshold"] == 80

    def test_update_filter_invalid(self, filter_instance):
        """Should return error for invalid filter name."""
        result = filter_instance.update_filter("nonexistent_filter")
        assert "error" in result

    def test_disable_all(self, filter_instance):
        """Should disable all filters."""
        filter_instance.disable_all()
        config = filter_instance.get_filter_config()
        for f in config["filters"].values():
            assert f["enabled"] is False

    def test_enable_all(self, filter_instance):
        """Should enable all filters."""
        filter_instance.disable_all()
        filter_instance.enable_all()
        config = filter_instance.get_filter_config()
        for f in config["filters"].values():
            assert f["enabled"] is True

    def test_reset_to_defaults(self, temp_config):
        """Should reset to default values."""
        # Create a fresh filter instance
        filter_inst = SuggestionFilter(config_path=temp_config)

        # Modify filters
        filter_inst.update_filter("min_confidence", threshold=90)
        filter_inst.update_filter("min_patterns", threshold=10)

        # Reset
        filter_inst.reset_to_defaults()

        config = filter_inst.get_filter_config()
        assert config["filters"]["min_confidence"]["threshold"] == 55
        assert config["filters"]["min_patterns"]["threshold"] == 3

    def test_save_and_load(self, temp_config):
        """Should persist configuration."""
        filter1 = SuggestionFilter(config_path=temp_config)
        filter1.update_filter("min_confidence", threshold=80)

        # Create new instance with same path
        filter2 = SuggestionFilter(config_path=temp_config)
        config = filter2.get_filter_config()
        assert config["filters"]["min_confidence"]["threshold"] == 80


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

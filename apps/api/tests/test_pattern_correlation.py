"""Tests for Pattern Correlation Module."""
import json
import tempfile
from pathlib import Path

import pytest

from api.services.pattern_correlation import (
    PatternCoOccurrence,
    CorrelationMatrix,
)


class TestPatternCoOccurrence:
    """Tests for PatternCoOccurrence dataclass."""

    def test_to_dict(self):
        co = PatternCoOccurrence(
            pattern_a="pattern_1",
            pattern_b="pattern_2",
            co_fires=10,
            co_hits=7,
            co_misses=3,
            correlation_score=0.7,
        )
        result = co.to_dict()
        assert result["pattern_a"] == "pattern_1"
        assert result["pattern_b"] == "pattern_2"
        assert result["co_fires"] == 10
        assert result["co_hits"] == 7
        assert result["correlation_score"] == 0.7

    def test_from_dict(self):
        data = {
            "pattern_a": "p1",
            "pattern_b": "p2",
            "co_fires": 5,
            "co_hits": 3,
            "co_misses": 2,
            "correlation_score": 0.6,
        }
        co = PatternCoOccurrence.from_dict(data)
        assert co.pattern_a == "p1"
        assert co.pattern_b == "p2"
        assert co.co_fires == 5
        assert co.co_hits == 3


class TestCorrelationMatrix:
    """Tests for CorrelationMatrix."""

    @pytest.fixture
    def temp_storage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "test_correlation.json"

    @pytest.fixture
    def matrix(self, temp_storage):
        class TestMatrix(CorrelationMatrix):
            def __post_init__(self):
                self._storage_path = temp_storage
                self._storage_path.parent.mkdir(parents=True, exist_ok=True)
                self._matrix = {}
                self._min_co_fires = 5
                self._dirty = False

        return TestMatrix()

    def test_normalize_key(self, matrix):
        """Keys should be normalized (sorted) to avoid duplicates."""
        key1 = matrix._normalize_key("b", "a")
        key2 = matrix._normalize_key("a", "b")
        assert key1 == key2
        assert key1 == ("a", "b")

    def test_update_correlation_single_pattern(self, matrix):
        """No update when only one pattern is active."""
        matrix.update_correlation(
            active_patterns=["pattern_1"],
            hit=True,
            suggested_numbers=[1, 2, 3],
        )
        assert len(matrix._matrix) == 0

    def test_update_correlation_two_patterns(self, matrix):
        """Update creates entry for pattern pair."""
        matrix.update_correlation(
            active_patterns=["pattern_1", "pattern_2"],
            hit=True,
            suggested_numbers=[1, 2, 3],
        )
        key = ("pattern_1", "pattern_2")
        assert key in matrix._matrix
        assert matrix._matrix[key].co_fires == 1
        assert matrix._matrix[key].co_hits == 1

    def test_update_correlation_multiple_times(self, matrix):
        """Multiple updates accumulate correctly."""
        for _ in range(3):
            matrix.update_correlation(
                active_patterns=["p1", "p2"],
                hit=True,
                suggested_numbers=[1, 2],
            )
        for _ in range(2):
            matrix.update_correlation(
                active_patterns=["p1", "p2"],
                hit=False,
                suggested_numbers=[1, 2],
            )

        key = ("p1", "p2")
        assert matrix._matrix[key].co_fires == 5
        assert matrix._matrix[key].co_hits == 3
        assert matrix._matrix[key].co_misses == 2
        assert matrix._matrix[key].correlation_score == 0.6

    def test_compute_correlation_boost_no_patterns(self, matrix):
        """Boost should be 1.0 with no patterns."""
        boost = matrix.compute_correlation_boost([])
        assert boost == 1.0

    def test_compute_correlation_boost_single_pattern(self, matrix):
        """Boost should be 1.0 with single pattern."""
        boost = matrix.compute_correlation_boost(["p1"])
        assert boost == 1.0

    def test_compute_correlation_boost_with_data(self, matrix):
        """Boost should reflect correlation."""
        # Build up enough data
        for _ in range(5):
            matrix.update_correlation(["p1", "p2"], hit=True, suggested_numbers=[])

        boost = matrix.compute_correlation_boost(["p1", "p2"])
        # With 100% hit rate, boost should be high
        assert boost > 1.0

    def test_get_agreement_score(self, matrix):
        """Agreement score should reflect pattern consensus."""
        contributions = [
            {"pattern_id": "p1", "numbers": [1, 2, 3]},
            {"pattern_id": "p2", "numbers": [2, 3, 4]},
            {"pattern_id": "p3", "numbers": [5, 6, 7]},
        ]
        # Number 2 is in 2/3 patterns
        score = matrix.get_agreement_score(contributions, target_number=2)
        assert score == pytest.approx(2/3)

        # Number 5 is in 1/3 patterns
        score = matrix.get_agreement_score(contributions, target_number=5)
        assert score == pytest.approx(1/3)

    def test_save_and_load(self, temp_storage):
        """Matrix should persist to disk correctly."""
        # Create and populate matrix
        matrix1 = CorrelationMatrix()
        matrix1._storage_path = temp_storage
        matrix1._matrix = {}
        matrix1._min_co_fires = 2
        matrix1._dirty = False

        for _ in range(3):
            matrix1.update_correlation(["p1", "p2"], hit=True, suggested_numbers=[])

        matrix1.save()
        assert temp_storage.exists()

        # Load in new instance
        matrix2 = CorrelationMatrix()
        matrix2._storage_path = temp_storage
        matrix2._matrix = {}
        matrix2._min_co_fires = 2
        matrix2._dirty = False
        matrix2._load()

        key = ("p1", "p2")
        assert key in matrix2._matrix
        assert matrix2._matrix[key].co_fires == 3

    def test_get_matrix_summary(self, matrix):
        """Summary should include all relevant data."""
        for _ in range(6):
            matrix.update_correlation(["p1", "p2"], hit=True, suggested_numbers=[])
        for _ in range(6):
            matrix.update_correlation(["p2", "p3"], hit=False, suggested_numbers=[])

        summary = matrix.get_matrix_summary()
        assert summary["total_pairs"] == 2
        assert summary["valid_pairs"] == 2
        assert len(summary["top_positive"]) > 0
        assert len(summary["top_negative"]) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

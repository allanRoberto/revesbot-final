"""Tests for Backtesting Module."""
import pytest
from unittest.mock import MagicMock, patch

from api.services.backtesting import (
    GaleLevelMetrics,
    PatternBacktestReport,
    BacktestEngine,
)


class TestGaleLevelMetrics:
    """Tests for GaleLevelMetrics dataclass."""

    def test_hit_rate_with_signals(self):
        metrics = GaleLevelMetrics(level=3, signals=10, hits=7)
        assert metrics.hit_rate == 0.7

    def test_hit_rate_zero_signals(self):
        metrics = GaleLevelMetrics(level=3, signals=0, hits=0)
        assert metrics.hit_rate == 0.0

    def test_to_dict(self):
        metrics = GaleLevelMetrics(level=5, signals=100, hits=70)
        result = metrics.to_dict()
        assert result["level"] == 5
        assert result["signals"] == 100
        assert result["hits"] == 70
        assert result["hit_rate"] == 0.7


class TestPatternBacktestReport:
    """Tests for PatternBacktestReport dataclass."""

    def test_best_gale_level_empty(self):
        report = PatternBacktestReport(pattern_id="test")
        assert report.best_gale_level == 1

    def test_best_gale_level_finds_70_percent(self):
        report = PatternBacktestReport(
            pattern_id="test",
            gale_metrics={
                1: GaleLevelMetrics(level=1, signals=100, hits=50),
                2: GaleLevelMetrics(level=2, signals=100, hits=65),
                3: GaleLevelMetrics(level=3, signals=100, hits=72),
            }
        )
        assert report.best_gale_level == 3

    def test_recommended_max_gale(self):
        report = PatternBacktestReport(
            pattern_id="test",
            gale_metrics={
                1: GaleLevelMetrics(level=1, signals=100, hits=40),
                2: GaleLevelMetrics(level=2, signals=100, hits=55),
                3: GaleLevelMetrics(level=3, signals=100, hits=58),  # Only 3% gain
            }
        )
        # Should stop at 2 since marginal gain at 3 is < 5%
        assert report.recommended_max_gale == 2

    def test_to_dict(self):
        report = PatternBacktestReport(
            pattern_id="test",
            total_signals=50,
            gale_metrics={
                1: GaleLevelMetrics(level=1, signals=50, hits=25),
            }
        )
        result = report.to_dict()
        assert result["pattern_id"] == "test"
        assert result["total_signals"] == 50
        assert "1" in result["gale_metrics"]


class TestBacktestEngine:
    """Tests for BacktestEngine."""

    @pytest.fixture
    def engine(self):
        return BacktestEngine()

    def test_evaluate_at_gale_level_hit(self, engine):
        history = [5, 10, 2, 7, 15, 20]  # 5 is at index 0
        suggestion = [1, 2, 3, 4, 5]  # 2 is at index 2

        # Looking at from_index=3, gale=2 should find 2 at index 2
        hit, number = engine._evaluate_at_gale_level(
            suggestion=suggestion,
            history=history,
            from_index=3,
            gale=2
        )
        assert hit is True
        assert number == 2

    def test_evaluate_at_gale_level_miss(self, engine):
        history = [5, 10, 25, 7, 15, 20]
        suggestion = [1, 2, 3, 4]  # None of these in recent history

        hit, number = engine._evaluate_at_gale_level(
            suggestion=suggestion,
            history=history,
            from_index=3,
            gale=3
        )
        assert hit is False
        assert number is None

    def test_evaluate_single_signal(self, engine):
        # history[0]=5, history[1]=10, history[2]=2, history[3]=7
        # from_index=3, so gale=1 looks at index 2 (value=2), which is in suggestion
        history = [5, 10, 2, 7, 15, 20]
        suggestion = [2, 3, 4]

        result = engine.evaluate_single_signal(
            suggestion=suggestion,
            history=history,
            from_index=3,
            gale_levels=[1, 2, 3],
        )

        assert result["hit"] is True
        assert result["first_hit"]["gale_level"] == 1  # Found at first attempt (index 2)
        assert result["first_hit"]["hit_number"] == 2

    def test_run_backtest_short_history(self, engine):
        mock_pattern_engine = MagicMock()

        result = engine.run_backtest(
            history=[1, 2, 3],  # Too short
            pattern_engine=mock_pattern_engine,
            gale_levels=[1, 2, 3, 5, 12],
        )

        assert result["available"] is False
        assert "error" in result

    def test_run_backtest_with_mocked_engine(self, engine):
        # Create a longer history
        history = list(range(100))

        mock_engine = MagicMock()
        mock_engine.evaluate.return_value = {
            "available": True,
            "suggestion": [1, 2, 3, 4, 5],
            "confidence": {"score": 70},
            "contributions": [
                {"pattern_id": "pattern_1"},
                {"pattern_id": "pattern_2"},
            ]
        }

        result = engine.run_backtest(
            history=history,
            pattern_engine=mock_engine,
            gale_levels=[1, 2, 3],
            max_entries=10,
        )

        assert result["available"] is True
        assert "summary" in result
        assert "overall_metrics" in result

    def test_generate_performance_report(self, engine):
        # Manually set up some reports
        engine._reports = {
            "p1": PatternBacktestReport(
                pattern_id="p1",
                total_signals=10,
                gale_metrics={
                    1: GaleLevelMetrics(level=1, signals=10, hits=5),
                    3: GaleLevelMetrics(level=3, signals=10, hits=8),
                }
            )
        }
        engine._overall_metrics = {
            1: GaleLevelMetrics(level=1, signals=10, hits=5),
            3: GaleLevelMetrics(level=3, signals=10, hits=8),
        }

        report = engine.generate_performance_report(
            signals_evaluated=10,
            signals_with_suggestion=10,
            gale_levels=[1, 3],
        )

        assert report["available"] is True
        assert report["summary"]["signals_evaluated"] == 10
        assert len(report["all_patterns"]) == 1

    def test_get_pattern_report_not_found(self, engine):
        result = engine.get_pattern_report("nonexistent")
        assert result["available"] is False
        assert "error" in result

    def test_get_pattern_report_found(self, engine):
        engine._reports["test_pattern"] = PatternBacktestReport(
            pattern_id="test_pattern",
            total_signals=5,
        )

        result = engine.get_pattern_report("test_pattern")
        assert result["available"] is True
        assert result["pattern_id"] == "test_pattern"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

import pytest

from apps.signals.orbit_engine.calibration import OrbitCalibration
from apps.signals.orbit_engine.ensemble import combine_probability_models
from apps.signals.orbit_engine.features import OrbitFeaturePipeline
from apps.signals.orbit_engine.ranker import OnlineCandidateRanker
from apps.signals.orbit_engine.survival import CandidateSurvivalModel
from shared.python.roulette.orbit.evidence_graph import EvidenceGraphConfig
from shared.python.roulette.orbit.orbit_builder import OrbitBuilder


def _decisions(total: int = 160):
    history = tuple(index % 37 for index in range(total))
    return tuple(
        OrbitBuilder(memory_occurrences=4).replay_decisions(
            history,
            horizon=3,
            warmup=80,
        )
    )


def _pipeline():
    return OrbitFeaturePipeline(EvidenceGraphConfig(max_hops=1))


def test_ranker_and_survival_train_predict_and_round_trip(tmp_path):
    decisions = _decisions()
    ranker = OnlineCandidateRanker(feature_pipeline=_pipeline()).fit(
        iter(decisions), max_decisions=8, batch_decisions=4
    )
    ranker_prediction = ranker.predict(decisions[8].context)
    assert sum(ranker_prediction.probabilities.values()) == pytest.approx(1.0)
    assert len(ranker_prediction.ranking) == 37

    ranker_path = tmp_path / "ranker.joblib"
    ranker.save(ranker_path)
    restored_ranker = OnlineCandidateRanker.load(ranker_path)
    assert restored_ranker.predict(decisions[8].context).ranking == ranker_prediction.ranking

    survival = CandidateSurvivalModel(pipeline=_pipeline()).fit(
        iter(decisions), horizon=3, max_decisions=8, batch_decisions=4
    )
    assert len(survival.predict(decisions[8].context).ranking) == 37
    survival_path = tmp_path / "survival.joblib"
    survival.save(survival_path)
    restored_survival = CandidateSurvivalModel.load(survival_path)
    assert restored_survival.predict(decisions[8].context).ranking == survival.predict(
        decisions[8].context
    ).ranking


def test_temperature_conformal_and_conservative_exclusions():
    scores = [
        {number: (4.0 if number == target else 0.0) for number in range(37)}
        for target in (1, 2, 3, 4)
    ]
    calibration = OrbitCalibration(alpha=0.10).fit(scores, [1, 2, 3, 4])
    probabilities, prediction_set = calibration.calibrate(scores[0])
    assert sum(probabilities.values()) == pytest.approx(1.0)
    assert 1 in prediction_set

    concentrated = {
        number: (0.5 if number == 0 else 0.5 / 36.0) for number in range(37)
    }
    ensemble = combine_probability_models([concentrated, concentrated, concentrated])
    assert len(ensemble.exclusions) == 25
    assert 0 not in ensemble.exclusions

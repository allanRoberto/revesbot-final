from __future__ import annotations

from api.routes.results_websocket import normalize_result_event


def test_normalize_result_event_preserves_full_result() -> None:
    event = normalize_result_event(
        '{"slug":"pragmatic-mega-roulette","result":"17",'
        '"full_result":{"value":17,"winning_multiplier":50,"slots":{"17":50}}}'
    )

    assert event["result"] == 17
    assert event["full_result"]["winning_multiplier"] == 50


def test_normalize_result_event_rejects_invalid_numbers() -> None:
    assert normalize_result_event({"slug": "mesa", "result": 37}) is None
    assert normalize_result_event({"slug": "mesa", "result": True}) is None
    assert normalize_result_event({"result": 17}) is None

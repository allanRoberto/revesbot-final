from __future__ import annotations

import asyncio
import json

import pytest

from api.services.jev_persistence import (
    JevRecordNotFoundError,
    load_analysis,
    persist_analysis,
    persist_evaluation,
)


def test_persistence_writes_one_private_json_record(tmp_path) -> None:
    record = {
        "analysis_id": "8f3bbcf2-11dc-4f50-aec5-4ff9001e7502",
        "historico_utilizado": [7, 7, 7],
        "grupos": {"grupo_1": [0, 1]},
        "payload_jev": {"model": "typesafe/jev-1.13"},
        "resposta_jev": {"id": "gen-1", "usage": {"cost": 0}},
    }
    destination = asyncio.run(persist_analysis(record, str(tmp_path)))

    assert destination.name == f"{record['analysis_id']}.json"
    assert json.loads(destination.read_text(encoding="utf-8")) == record
    assert [path for path in tmp_path.iterdir() if path.suffix == ".json"] == [destination]


def test_persistence_refuses_non_finite_json(tmp_path) -> None:
    with pytest.raises(ValueError):
        asyncio.run(
            persist_analysis(
                {"analysis_id": "invalid", "probability": float("nan")},
                str(tmp_path),
            )
        )
    assert list(tmp_path.iterdir()) == []


def test_persistence_loads_analysis_and_writes_separate_evaluation(tmp_path) -> None:
    analysis_id = "8f3bbcf2-11dc-4f50-aec5-4ff9001e7502"
    evaluation_id = "f266f9fb-ef32-4398-ada7-a269d14f697d"
    analysis = {"analysis_id": analysis_id, "analysis_type": "number_ranking"}
    asyncio.run(persist_analysis(analysis, str(tmp_path)))
    assert asyncio.run(load_analysis(analysis_id, str(tmp_path))) == analysis

    evaluation = {
        "analysis_id": analysis_id,
        "evaluation_id": evaluation_id,
        "analysis_type": "number_ranking_evaluation",
    }
    destination = asyncio.run(persist_evaluation(evaluation, str(tmp_path)))
    assert destination.name == f"{analysis_id}.evaluation.{evaluation_id}.json"
    assert json.loads(destination.read_text(encoding="utf-8")) == evaluation


def test_load_analysis_does_not_accept_unknown_or_non_uuid_paths(tmp_path) -> None:
    with pytest.raises(JevRecordNotFoundError):
        asyncio.run(
            load_analysis("8f3bbcf2-11dc-4f50-aec5-4ff9001e7502", str(tmp_path))
        )
    with pytest.raises(ValueError):
        asyncio.run(load_analysis("../private", str(tmp_path)))

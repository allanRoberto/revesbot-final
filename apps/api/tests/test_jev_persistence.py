from __future__ import annotations

import asyncio
import json

import pytest

from api.services.jev_persistence import persist_analysis


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

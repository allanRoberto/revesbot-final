from __future__ import annotations

import asyncio
import json

from api.services import monitor_replay


def test_replay_history_to_channel_publishes_in_chronological_order(monkeypatch) -> None:
    published: list[tuple[str, dict]] = []

    async def fake_fetch_history_desc(roulette_id: str, limit: int) -> list[int]:
        assert roulette_id == "pragmatic-auto-roulette"
        assert limit == 3
        return [9, 8, 7]

    class _FakeRedis:
        async def publish(self, channel: str, payload: str) -> int:
            published.append((channel, json.loads(payload)))
            return 1

    monkeypatch.setattr(monitor_replay, "fetch_history_desc", fake_fetch_history_desc)
    monkeypatch.setattr(monitor_replay, "r", _FakeRedis())

    result = asyncio.run(
        monitor_replay.replay_history_to_channel(
            roulette_id="pragmatic-auto-roulette",
            limit=3,
            delay_ms=0,
        )
    )

    assert result["state"] == "completed"
    assert result["total_numbers"] == 3
    assert result["published_numbers"] == 3
    assert [channel for channel, _payload in published] == [
        monitor_replay.SIMULATION_RESULT_CHANNEL,
        monitor_replay.SIMULATION_RESULT_CHANNEL,
        monitor_replay.SIMULATION_RESULT_CHANNEL,
    ]
    assert [payload["result"] for _channel, payload in published] == [7, 8, 9]
    assert all(payload["simulation"] is True for _channel, payload in published)


from __future__ import annotations

import pytest

from contextual_ranking import engine as ranking_engine
from contextual_pairs.tests.scripted import ScriptedRanking


@pytest.fixture
def scripted(monkeypatch):
    """Replace the ranking engine by a scripted one: ``scripted([top, top, ...])``."""
    def install(tops):
        fake = ScriptedRanking(tops)
        monkeypatch.setattr(ranking_engine, "process", fake.process)
        monkeypatch.setattr(ranking_engine, "rebuild", fake.rebuild)
        return fake
    return install

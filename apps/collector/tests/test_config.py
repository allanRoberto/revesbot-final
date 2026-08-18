from __future__ import annotations

import pytest

from apps.collector.collector.config import CollectorSettings


def test_requires_connection_strings(monkeypatch):
    monkeypatch.delenv("MONGO_URL", raising=False)
    monkeypatch.delenv("REDIS_CONNECT", raising=False)
    with pytest.raises(RuntimeError, match="MONGO_URL"):
        CollectorSettings.from_env()


def test_uses_isolated_database_from_environment(monkeypatch):
    monkeypatch.setenv("MONGO_URL", "mongodb://127.0.0.1:27017")
    monkeypatch.setenv("REDIS_CONNECT", "redis://127.0.0.1:6379")
    monkeypatch.setenv("MONGO_DATABASE", "roleta_db_collector_test")
    monkeypatch.setenv("PRAGMATIC_SUBSCRIBE_KEYS", "225,237")
    settings = CollectorSettings.from_env()
    assert settings.mongo_database == "roleta_db_collector_test"
    assert settings.subscribe_keys == ("225", "237")

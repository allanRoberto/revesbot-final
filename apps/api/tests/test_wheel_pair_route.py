from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import roulette_history
from api.routes.wheel_pair import HISTORY_ROULETTES, HISTORY_ROULETTE_BY_SLUG, _wheel_pair_asset_version, router


class _UnexpectedDatabase:
    def __getattr__(self, name):
        raise AssertionError("Rendering the wheel-pair page must not query history")


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.mark.parametrize("slug", [None, "pragmatic-brazilian-roulette", "pragmatic-mega-roulette"])
def test_page_renders_selected_roulette_and_versioned_assets_without_database(monkeypatch, slug):
    monkeypatch.setattr(roulette_history, "history_coll", _UnexpectedDatabase())
    response = _client().get("/contagem-casas", params={"slug": slug} if slug else {})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    expected_slug = slug or "pragmatic-auto-roulette"
    assert response.context["slug"] == expected_slug
    assert response.context["roulette"] == HISTORY_ROULETTE_BY_SLUG[expected_slug]
    assert response.context["roulettes"] == HISTORY_ROULETTES
    version = _wheel_pair_asset_version()
    assert response.context["asset_version"] == version
    assert f'href="/static/css/pages/wheel-pair.css?v={version}"' in response.text
    assert f'src="/static/js/pages/wheel-pair.js?v={version}"' in response.text
    assert "{{" not in response.text


@pytest.mark.parametrize("slug", ["", "unknown-roulette", "../history", "<script>"])
def test_page_rejects_unmonitored_roulette(slug):
    response = _client().get("/contagem-casas", params={"slug": slug})

    assert response.status_code == 404
    assert response.json() == {"detail": "Roleta não monitorada"}

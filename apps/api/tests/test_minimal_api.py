from __future__ import annotations

from fastapi.testclient import TestClient

from api.minimal_main import app


def test_minimal_api_exposes_only_expected_functional_routes() -> None:
    paths = {route.path for route in app.routes}

    assert paths == {
        "/api/roulettes-list",
        "/history-detailed/{slug}",
        "/history/{slug}",
        "/history-app/{slug}",
        "/ws",
        "/webhooks/pixgo",
        "/static",
    }
    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None


def test_history_html_uses_external_assets_and_docs_are_disabled() -> None:
    client = TestClient(app)
    response = client.get(
        "/history/pragmatic-auto-roulette",
        headers={"Accept": "text/html"},
    )

    assert response.status_code == 200
    assert '<script type="module" src="/static/js/pages/history.js?v=' in response.text
    assert 'id="grid-columns"' in response.text
    assert "Números por linha" in response.text
    assert 'id="number-context-panel"' in response.text
    assert "Números atrás" in response.text
    assert "Números à frente" in response.text
    assert 'id="context-summary"' not in response.text
    assert 'id="context-occurrences"' not in response.text
    assert "<style" not in response.text
    assert client.get("/docs").status_code == 404

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.contextual_similarity import router


def test_contextual_similarity_page_renders_without_loading_history():
    app = FastAPI()
    app.include_router(router)

    response = TestClient(app).get("/analise-similaridade-contextual")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Similaridade contextual" in response.text
    assert 'src="/static/js/pages/contextual-similarity.js?v=20261108-posterior-order"' in response.text
    assert 'href="/static/css/pages/contextual-similarity.css?v=20261108-signal-thermometer"' in response.text
    assert "{{" not in response.text

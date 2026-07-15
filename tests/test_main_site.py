from fastapi.testclient import TestClient

from ainulindale_api.main import app

client = TestClient(app)

def test_privacy_html_is_reachable():
    response = client.get("/privacy.html")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")

def test_terms_html_is_reachable():
    response = client.get("/terms.html")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")

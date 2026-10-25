from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from ainulindale_api.apps.home import models
from ainulindale_api.main import app


@pytest.fixture
def client():
    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture
def allowlisted_session():
    return models.HomeSession(
        id="session-dana-alerta",
        user_id="user-dana",
        email="diederich@gmail.com",
        name="Dana M. Diederich",
        is_authenticated=True,
    )


@pytest.fixture
def non_allowlisted_session():
    return models.HomeSession(
        id="session-stranger-alerta",
        user_id="user-stranger",
        email="stranger@example.com",
        name="Unauthorized User",
        is_authenticated=True,
    )


@pytest.fixture
def mock_alerta_db():
    with (
        patch(
            "ainulindale_api.apps.home.models.get_session",
            new_callable=AsyncMock,
        ) as mock_get_session,
        patch(
            "ainulindale_api.apps.home.models.get_user",
            new_callable=AsyncMock,
        ) as mock_get_user,
    ):
        mock_get_session.return_value = None
        mock_get_user.return_value = None
        yield {"get_session": mock_get_session, "get_user": mock_get_user}


def test_home_alerta_unauthenticated_access_blocked(client, mock_alerta_db):
    client.cookies.clear()
    mock_alerta_db["get_session"].return_value = None

    # Browser GET /home/alerta redirects to login
    res_root = client.get("/home/alerta", follow_redirects=False)
    assert res_root.status_code == 303
    assert res_root.headers["location"] == "/home/alerta/"

    res_slash = client.get("/home/alerta/", follow_redirects=False)
    assert res_slash.status_code == 303
    assert res_slash.headers["location"] == "/home/auth/google/login"

    # API request returns 401 JSON
    res_api = client.get("/home/alerta/api/alerts")
    assert res_api.status_code == 401
    assert res_api.json()["detail"] == "Authentication required"

    # JSON accept header returns 401 JSON
    res_json = client.get(
        "/home/alerta/config.json", headers={"Accept": "application/json"}
    )
    assert res_json.status_code == 401
    assert res_json.json()["detail"] == "Authentication required"


def test_home_alerta_non_allowlisted_email_forbidden(
    client, mock_alerta_db, non_allowlisted_session
):
    client.cookies.set("ainulindale_home_session", "session-stranger-alerta")
    mock_alerta_db["get_session"].return_value = non_allowlisted_session

    res = client.get("/home/alerta/", follow_redirects=False)
    assert res.status_code == 403
    assert "Access Restricted" in res.text
    assert "stranger@example.com" in res.text


def test_home_alerta_login_redirect(client):
    res = client.get("/home/alerta/login", follow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == "/home/alerta/"


def test_home_alerta_config_json(client, mock_alerta_db, allowlisted_session):
    client.cookies.set("ainulindale_home_session", "session-dana-alerta")
    mock_alerta_db["get_session"].return_value = allowlisted_session

    res = client.get("/home/alerta/config.json")
    assert res.status_code == 200
    data = res.json()
    assert data["endpoint"] == "/home/alerta/api"
    assert data["base_path"] == "/home/alerta"
    assert data["auth_required"] is False
    assert data["allow_readonly"] is True
    assert data["filter"] == {"status": ["open", "ack"]}
    assert "severity" in data["columns"]
    assert "grafana" in data["columns"]


@patch("ainulindale_api.apps.home.alerta.httpx.AsyncClient")
def test_home_alerta_html_rewriting(
    mock_client_cls, client, mock_alerta_db, allowlisted_session
):
    client.cookies.set("ainulindale_home_session", "session-dana-alerta")
    mock_alerta_db["get_session"].return_value = allowlisted_session

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "text/html; charset=utf-8"}
    mock_resp.text = (
        "<!DOCTYPE html><html><head>"
        '<link href="/css/app.3c213ee5.css" rel="stylesheet">'
        '<link rel="icon" href="/favicon-32x32.png">'
        '<meta name="msapplication-TileImage" content="/mstile-144x144.png">'
        '</head><body><script src="/js/app.aa028083.js"></script></body></html>'
    )
    mock_async = AsyncMock()
    mock_async.request.return_value = mock_resp
    mock_client_cls.return_value.__aenter__.return_value = mock_async

    res = client.get("/home/alerta/")
    assert res.status_code == 200
    # Root paths rewritten to /home/alerta/
    assert 'href="/home/alerta/css/app.3c213ee5.css"' in res.text
    assert 'href="/home/alerta/favicon-32x32.png"' in res.text
    assert 'content="/home/alerta/mstile-144x144.png"' in res.text
    assert 'src="/home/alerta/js/app.aa028083.js"' in res.text
    # No bare root paths remain
    assert 'href="/css/' not in res.text
    assert 'src="/js/' not in res.text


@patch("ainulindale_api.apps.home.alerta.httpx.AsyncClient")
def test_home_alerta_js_rewriting(
    mock_client_cls, client, mock_alerta_db, allowlisted_session
):
    client.cookies.set("ainulindale_home_session", "session-dana-alerta")
    mock_alerta_db["get_session"].return_value = allowlisted_session

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "application/javascript"}
    mock_resp.text = (
        'function init(){c.p="/";console.log("loader");}'
        'var e="/";return this.$http.get("".concat(e,"config.json"))'
        ",alarm_model:{},auth_required:!0,allow_readonly:!1"
    )
    mock_async = AsyncMock()
    mock_async.request.return_value = mock_resp
    mock_client_cls.return_value.__aenter__.return_value = mock_async

    res = client.get("/home/alerta/js/app.aa028083.js")
    assert res.status_code == 200
    assert 'c.p="/home/alerta/"' in res.text
    assert (
        'var e="/home/alerta/";return this.$http.get("".concat(e,"config.json"))'
        in res.text
    )
    assert "auth_required:!1" in res.text
    assert "auth_required:!0" not in res.text


@patch("ainulindale_api.apps.home.alerta.httpx.AsyncClient")
def test_home_alerta_api_proxying_and_sanitization(
    mock_client_cls, client, mock_alerta_db, allowlisted_session
):
    client.cookies.set("ainulindale_home_session", "session-dana-alerta")
    mock_alerta_db["get_session"].return_value = allowlisted_session

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "application/json"}
    mock_resp.text = (
        '{"status":"ok",'
        '"endpoint":"https, https://192.168.1.247:8080/api",'
        '"alerts":[{"id":"alert-1",'
        '"href":"https, https:/192.168.1.247:8080/api/alert/alert-1"}]}'
    )
    mock_async = AsyncMock()
    mock_async.request.return_value = mock_resp
    mock_client_cls.return_value.__aenter__.return_value = mock_async

    res = client.get("/home/alerta/api/alerts")
    assert res.status_code == 200
    assert "192.168.1.247:8080" not in res.text
    assert "/home/alerta/api/alert/alert-1" in res.text
    assert res.json()["endpoint"] == "/home/alerta/api"


@patch("ainulindale_api.apps.home.alerta.httpx.AsyncClient")
def test_home_alerta_upstream_error_handled_gracefully(
    mock_client_cls, client, mock_alerta_db, allowlisted_session
):
    client.cookies.set("ainulindale_home_session", "session-dana-alerta")
    mock_alerta_db["get_session"].return_value = allowlisted_session

    mock_async = AsyncMock()
    mock_async.request.side_effect = httpx.ConnectError("Connection refused")
    mock_client_cls.return_value.__aenter__.return_value = mock_async

    # HTML browser request returns friendly 502 page
    res_html = client.get("/home/alerta/")
    assert res_html.status_code == 502
    assert "Alerta Service Unavailable" in res_html.text

    # API request returns 502 JSON
    res_api = client.get("/home/alerta/api/alerts")
    assert res_api.status_code == 502
    assert "Alerta upstream service unavailable" in res_api.json()["detail"]

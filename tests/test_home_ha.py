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
def allowlisted_dana_session():
    return models.HomeSession(
        id="session-dana-ha",
        user_id="user-dana",
        email="diederich@gmail.com",
        name="Dana M. Diederich",
        is_authenticated=True,
    )


@pytest.fixture
def allowlisted_michelle_session():
    return models.HomeSession(
        id="session-michelle-ha",
        user_id="user-michelle",
        email="msdiederich@gmail.com",
        name="Michelle Diederich",
        is_authenticated=True,
    )


@pytest.fixture
def non_allowlisted_session():
    return models.HomeSession(
        id="session-stranger-ha",
        user_id="user-stranger",
        email="stranger@example.com",
        name="Unauthorized User",
        is_authenticated=True,
    )


@pytest.fixture
def mock_ha_db():
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


def test_home_ha_unauthenticated_access_blocked(client, mock_ha_db):
    client.cookies.clear()
    mock_ha_db["get_session"].return_value = None

    # Browser GET /home/ha redirects to /home/ha/
    res_root = client.get("/home/ha", follow_redirects=False)
    assert res_root.status_code == 303
    assert res_root.headers["location"] == "/home/ha/"

    # GET /home/ha/ redirects to Google login
    res_slash = client.get("/home/ha/", follow_redirects=False)
    assert res_slash.status_code == 303
    assert "/home/auth/google/login" in res_slash.headers["location"]

    # API request returns 401 JSON
    res_api = client.get("/home/ha/api/states")
    assert res_api.status_code == 401
    assert res_api.json()["detail"] == "Authentication required"


def test_home_ha_non_allowlisted_email_forbidden(
    client, mock_ha_db, non_allowlisted_session
):
    client.cookies.set("ainulindale_home_session", "session-stranger-ha")
    mock_ha_db["get_session"].return_value = non_allowlisted_session

    res = client.get("/home/ha/", follow_redirects=False)
    assert res.status_code == 403
    assert "Access Restricted" in res.text
    assert "stranger@example.com" in res.text


def test_home_ha_authenticated_dana_forwarding_and_html_rewrite(
    client, mock_ha_db, allowlisted_dana_session
):
    client.cookies.set("ainulindale_home_session", "session-dana-ha")
    mock_ha_db["get_session"].return_value = allowlisted_dana_session

    upstream_raw_html = (
        "<!DOCTYPE html><html><head>"
        '<link rel="manifest" href="/manifest.json">'
        '<link rel="icon" href="/static/icons/favicon.ico">'
        '<link rel="modulepreload" href="/frontend_latest/core.js">'
        "</head><body><home-assistant></home-assistant></body></html>"
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {
        "content-type": "text/html; charset=utf-8",
        "content-length": str(len(upstream_raw_html)),
        "accept-ranges": "bytes",
    }
    mock_resp.text = upstream_raw_html

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_resp

        res = client.get("/home/ha/")
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/html")

        # Verify forwarded headers
        call_kwargs = mock_req.call_args.kwargs
        assert call_kwargs["headers"]["x-forwarded-user"] == "diederich@gmail.com"
        assert call_kwargs["headers"]["x-forwarded-email"] == "diederich@gmail.com"
        assert call_kwargs["headers"]["x-forwarded-prefix"] == "/home/ha"
        assert "accept-encoding" not in call_kwargs["headers"]

        # Verify rewritten HTML
        body = res.text
        assert 'href="/home/ha/manifest.json"' in body
        assert 'href="/home/ha/static/icons/favicon.ico"' in body
        assert 'href="/home/ha/frontend_latest/core.js"' in body


def test_home_ha_authenticated_michelle_forwarding(
    client, mock_ha_db, allowlisted_michelle_session
):
    client.cookies.set("ainulindale_home_session", "session-michelle-ha")
    mock_ha_db["get_session"].return_value = allowlisted_michelle_session

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "application/json"}
    mock_resp.content = b'{"status": "ok"}'

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_resp

        res = client.get("/home/ha/api/config")
        assert res.status_code == 200
        call_kwargs = mock_req.call_args.kwargs
        assert call_kwargs["headers"]["x-forwarded-user"] == "msdiederich@gmail.com"
        assert call_kwargs["headers"]["x-forwarded-email"] == "msdiederich@gmail.com"


def test_home_ha_javascript_origin_rewrite(
    client, mock_ha_db, allowlisted_dana_session
):
    client.cookies.set("ainulindale_home_session", "session-dana-ha")
    mock_ha_db["get_session"].return_value = allowlisted_dana_session

    upstream_js = (
        'const R=`${location.protocol}//${location.host}`;o.p="/frontend_latest/";'
        'fetch("/auth/providers");fetch("/static/translations/en.json");'
        "url(${(0,a.iz)(/static/)}fonts/roboto/Roboto-Regular.woff2);"
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "application/javascript"}
    mock_resp.text = upstream_js

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_resp

        res = client.get("/home/ha/frontend_latest/core.js")
        assert res.status_code == 200
        body = res.text
        assert "const R=`${location.protocol}//${location.host}/home/ha`" in body
        assert 'o.p="/home/ha/frontend_latest/"' in body
        assert 'fetch("/home/ha/auth/providers")' in body
        assert 'fetch("/home/ha/static/translations/en.json")' in body
        # Ensure regex literal (/static/) is NOT corrupted to (/home/ha/static/)
        assert "(/static/)" in body
        assert "(/home/ha/static/)" not in body


def test_home_ha_css_rewrite(client, mock_ha_db, allowlisted_dana_session):
    client.cookies.set("ainulindale_home_session", "session-dana-ha")
    mock_ha_db["get_session"].return_value = allowlisted_dana_session

    upstream_css = "body { background: url(/static/fonts/roboto.woff2); }"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "text/css"}
    mock_resp.text = upstream_css

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_resp

        res = client.get("/home/ha/static/app.css")
        assert res.status_code == 200
        assert "url(/home/ha/static/fonts/roboto.woff2)" in res.text


def test_home_ha_upstream_failure_returns_502(
    client, mock_ha_db, allowlisted_dana_session
):
    client.cookies.set("ainulindale_home_session", "session-dana-ha")
    mock_ha_db["get_session"].return_value = allowlisted_dana_session

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.side_effect = httpx.ConnectError("Connection refused")

        # HTML request returns 502 status page
        res = client.get("/home/ha/")
        assert res.status_code == 502
        assert "Home Assistant Unavailable" in res.text

        # API request returns 502 JSON
        res_api = client.get("/home/ha/api/states")
        assert res_api.status_code == 502
        assert "unavailable" in res_api.json()["detail"].lower()


def test_home_ha_camera_proxy_root_unauthenticated_blocked(client, mock_ha_db):
    client.cookies.clear()
    mock_ha_db["get_session"].return_value = None

    # Missing session and token -> 401
    res = client.get("/api/camera_proxy/camera.yard_near_shed_snapshots_clear")
    assert res.status_code == 401
    assert res.json()["detail"] == "Authentication required"


def test_home_ha_camera_proxy_root_with_token(client, mock_ha_db):
    client.cookies.clear()
    mock_ha_db["get_session"].return_value = None

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "image/jpeg", "content-length": "100"}
    mock_resp.content = b"fake-jpeg-bytes"

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_resp

        res = client.get(
            "/api/camera_proxy/camera.yard_near_shed_snapshots_clear?token=valid-token"
        )
        assert res.status_code == 200
        assert res.headers["content-type"] == "image/jpeg"
        assert res.content == b"fake-jpeg-bytes"
        assert mock_req.call_args.kwargs["url"].endswith("?token=valid-token")


def test_home_ha_camera_stream_root_with_token(client, mock_ha_db):
    client.cookies.clear()
    mock_ha_db["get_session"].return_value = None

    async def fake_aiter_raw():
        yield b"--frameboundary\r\nContent-Type: image/jpeg\r\n\r\nframe1\r\n"
        yield b"--frameboundary\r\nContent-Type: image/jpeg\r\n\r\nframe2\r\n"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {
        "content-type": "multipart/x-mixed-replace; boundary=--frameboundary"
    }
    mock_resp.aiter_raw = fake_aiter_raw
    mock_resp.aclose = AsyncMock()

    with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = mock_resp

        res = client.get(
            "/api/camera_proxy_stream/camera.yard_near_shed_snapshots_clear?token=valid-token"
        )
        assert res.status_code == 200
        assert "multipart/x-mixed-replace" in res.headers["content-type"]
        assert b"frame1" in res.content
        assert b"frame2" in res.content


def test_home_ha_panel_redirects(client):
    # /live-cameras/yard -> 307 to /home/ha/live-cameras/yard
    res = client.get("/live-cameras/yard", follow_redirects=False)
    assert res.status_code == 307
    assert res.headers["location"] == "/home/ha/live-cameras/yard"

    # /live-cameras -> 307 to /home/ha/live-cameras
    res_root = client.get("/live-cameras", follow_redirects=False)
    assert res_root.status_code == 307
    assert res_root.headers["location"] == "/home/ha/live-cameras"

    # /lovelace -> 307 to /home/ha/lovelace
    res_love = client.get("/lovelace", follow_redirects=False)
    assert res_love.status_code == 307
    assert res_love.headers["location"] == "/home/ha/lovelace"


def test_home_ha_javascript_router_and_pushstate_rewrite(
    client, mock_ha_db, allowlisted_dana_session
):
    client.cookies.set("ainulindale_home_session", "session-dana-ha")
    mock_ha_db["get_session"].return_value = allowlisted_dana_session

    upstream_js = (
        "const A=()=>location.pathname;"
        'r.pushState(h(t?.data,n.G.location.pathname),"",e);'
        'r.replaceState(h(n,o),"",e);'
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "application/javascript"}
    mock_resp.text = upstream_js

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_resp

        res = client.get("/home/ha/frontend_latest/app.js")
        assert res.status_code == 200
        body = res.text
        expected_push = (
            'r.pushState(h(t?.data,n.G.location.pathname),"",'
            '(typeof e==="string"&&e.startsWith("/")&&!e.startsWith("/home/ha")'
            '?"/home/ha"+e:e))'
        )
        assert expected_push in body

        expected_replace = (
            'r.replaceState(h(n,o),"",'
            '(typeof e==="string"&&e.startsWith("/")&&!e.startsWith("/home/ha")'
            '?"/home/ha"+e:e))'
        )
        assert expected_replace in body

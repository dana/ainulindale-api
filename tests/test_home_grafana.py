from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from ainulindale_api.apps.home import auth, models
from ainulindale_api.main import app


@pytest.fixture
def client():
    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture
def allowlisted_dana_session():
    return models.HomeSession(
        id="session-dana-grafana",
        user_id="user-dana",
        email="diederich@gmail.com",
        name="Dana M. Diederich",
        is_authenticated=True,
    )


@pytest.fixture
def non_allowlisted_session():
    return models.HomeSession(
        id="session-stranger-grafana",
        user_id="user-stranger",
        email="stranger@example.com",
        name="Unauthorized User",
        is_authenticated=True,
    )


@pytest.fixture
def mock_grafana_db():
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
        yield mock_get_session, mock_get_user


def test_home_grafana_root_redirect(client):
    """Test /home/grafana redirects with 303 to /home/grafana/."""
    response = client.get("/home/grafana", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/home/grafana/"


def test_home_grafana_unauthenticated_access_blocked(client, mock_grafana_db):
    """Unauthenticated access redirects HTML to Google login and returns 401 for API."""
    mock_get_session, _ = mock_grafana_db
    mock_get_session.return_value = None

    # HTML request redirects
    res_html = client.get(
        "/home/grafana/",
        headers={"accept": "text/html"},
        follow_redirects=False,
    )
    assert res_html.status_code == 303
    assert res_html.headers["location"] == "/home/auth/google/login"

    # API request returns 401
    res_api = client.get(
        "/home/grafana/api/health",
        headers={"accept": "application/json"},
        follow_redirects=False,
    )
    assert res_api.status_code == 401
    assert res_api.json()["detail"] == "Authentication required"


def test_home_grafana_non_allowlisted_email_forbidden(
    client, mock_grafana_db, non_allowlisted_session
):
    """Non-allowlisted accounts get 403 Forbidden with custom unauthorized page."""
    mock_get_session, mock_get_user = mock_grafana_db
    mock_get_session.return_value = non_allowlisted_session
    mock_get_user.return_value = None

    client.cookies.set(auth.COOKIE_NAME, non_allowlisted_session.id)
    response = client.get("/home/grafana/")
    assert response.status_code == 403
    assert "Access Restricted" in response.text
    assert "stranger@example.com" in response.text


def test_home_grafana_http_proxying_and_headers(
    client, mock_grafana_db, allowlisted_dana_session
):
    """Authenticated requests forward X-Webauth-User and client IP to upstream."""
    mock_get_session, mock_get_user = mock_grafana_db
    mock_get_session.return_value = allowlisted_dana_session
    mock_get_user.return_value = None

    client.cookies.set(auth.COOKIE_NAME, allowlisted_dana_session.id)

    mock_resp = httpx.Response(
        status_code=200,
        text=(
            '<!DOCTYPE html><base href="/home/grafana/" />'
            "<html><head><title>Grafana</title></head><body>Dashboard</body></html>"
        ),
        headers={"content-type": "text/html; charset=utf-8"},
    )

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = mock_resp
        response = client.get("/home/grafana/d/homelab-git-fleet")

        assert response.status_code == 200
        assert "Dashboard" in response.text

        # Verify forwarded headers
        call_kwargs = mock_request.call_args.kwargs
        assert call_kwargs["method"] == "GET"
        assert "/d/homelab-git-fleet" in call_kwargs["url"]
        headers = call_kwargs["headers"]
        assert headers["x-webauth-user"] == "diederich@gmail.com"
        assert headers["x-forwarded-prefix"] == "/home/grafana"
        assert headers["x-forwarded-proto"] == "https"


def test_home_grafana_location_redirect_rewriting(
    client, mock_grafana_db, allowlisted_dana_session
):
    """Upstream redirect locations with internal base are rewritten to /home/grafana."""
    mock_get_session, mock_get_user = mock_grafana_db
    mock_get_session.return_value = allowlisted_dana_session
    mock_get_user.return_value = None

    client.cookies.set(auth.COOKIE_NAME, allowlisted_dana_session.id)

    mock_resp = httpx.Response(
        status_code=302,
        headers={"location": "http://192.168.1.247:3000/d/homelab-fleet-reachability"},
    )

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = mock_resp
        response = client.get("/home/grafana/dashboards", follow_redirects=False)

        assert response.status_code == 302
        assert (
            response.headers["location"] == "/home/grafana/d/homelab-fleet-reachability"
        )


def test_home_grafana_upstream_error_handled_gracefully(
    client, mock_grafana_db, allowlisted_dana_session
):
    """When Grafana daemon is unreachable, returns styled 502 page."""
    mock_get_session, mock_get_user = mock_grafana_db
    mock_get_session.return_value = allowlisted_dana_session
    mock_get_user.return_value = None

    client.cookies.set(auth.COOKIE_NAME, allowlisted_dana_session.id)

    with patch(
        "httpx.AsyncClient.request",
        side_effect=httpx.ConnectError("Connection refused"),
    ):
        response = client.get("/home/grafana/")
        assert response.status_code == 502
        assert "Grafana Unavailable" in response.text

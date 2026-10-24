from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from ainulindale_api.apps.home import models
from ainulindale_api.main import app


@pytest.fixture
def client():
    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture
def fake_pending_session():
    return models.HomeSession(
        id="session-pending-123",
        state="state-123",
        nonce="nonce-123",
        is_authenticated=False,
    )


@pytest.fixture
def fake_authenticated_session():
    return models.HomeSession(
        id="session-auth-123",
        user_id="user-123",
        email="diederich@gmail.com",
        name="Dana M. Diederich",
        is_authenticated=True,
    )


@pytest.fixture
def mock_home_db(fake_pending_session, fake_authenticated_session):
    with (
        patch(
            "ainulindale_api.apps.home.models.get_session",
            new_callable=AsyncMock,
        ) as mock_get_session,
        patch(
            "ainulindale_api.apps.home.models.create_session",
            new_callable=AsyncMock,
        ) as mock_create_session,
        patch(
            "ainulindale_api.apps.home.models.update_session",
            new_callable=AsyncMock,
        ) as mock_update_session,
        patch(
            "ainulindale_api.apps.home.models.delete_session",
            new_callable=AsyncMock,
        ) as mock_delete_session,
        patch(
            "ainulindale_api.apps.home.models.get_user_by_sub",
            new_callable=AsyncMock,
        ) as mock_get_user_sub,
        patch(
            "ainulindale_api.apps.home.models.create_user",
            new_callable=AsyncMock,
        ) as mock_create_user,
        patch(
            "ainulindale_api.apps.home.models.get_user",
            new_callable=AsyncMock,
        ) as mock_get_user,
        patch(
            "ainulindale_api.apps.home.models.update_user_login",
            new_callable=AsyncMock,
        ) as mock_update_user_login,
    ):
        mock_get_session.return_value = fake_pending_session
        mock_create_session.return_value = fake_pending_session
        mock_get_user_sub.return_value = models.HomeUser(
            google_sub="sub-dana",
            email="diederich@gmail.com",
            name="Dana M. Diederich",
        )
        mock_get_user.return_value = models.HomeUser(
            _id="user-123",
            google_sub="sub-dana",
            email="diederich@gmail.com",
            name="Dana M. Diederich",
        )

        yield {
            "get_session": mock_get_session,
            "create_session": mock_create_session,
            "update_session": mock_update_session,
            "delete_session": mock_delete_session,
            "get_user_by_sub": mock_get_user_sub,
            "create_user": mock_create_user,
            "get_user": mock_get_user,
            "update_user_login": mock_update_user_login,
        }


def test_home_unauthenticated_redirects_to_login(client, mock_home_db):
    client.cookies.clear()
    mock_home_db["get_session"].return_value = None

    response = client.get("/home", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/home/auth/google/login"

    response_slash = client.get("/home/", follow_redirects=False)
    assert response_slash.status_code == 303
    assert response_slash.headers["location"] == "/home/auth/google/login"


def test_home_login_redirects_to_google(client, mock_home_db, monkeypatch):
    test_id = "test-client-id.apps.googleusercontent.com"
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", test_id)
    response = client.get("/home/auth/google/login", follow_redirects=False)
    assert response.status_code == 303
    loc = response.headers["location"]
    assert "https://accounts.google.com/o/oauth2/v2/auth" in loc
    assert "client_id=test-client-id.apps.googleusercontent.com" in loc
    assert "ainulindale_home_session" in response.cookies


def test_home_callback_state_mismatch(client, mock_home_db, monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-secret")
    client.cookies.set("ainulindale_home_session", "session-pending-123")

    # Mismatched state should return 400
    response = client.get(
        "/home/auth/google/callback?code=fake-code&state=wrong-state",
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "mismatch" in response.json()["detail"].lower()


@patch("ainulindale_api.apps.home.auth.httpx.AsyncClient")
@patch("ainulindale_api.apps.home.auth.id_token")
@patch("ainulindale_api.apps.home.auth.google_requests.Request")
def test_home_callback_unauthorized_email(
    mock_req, mock_id_token, mock_async_client, client, mock_home_db, monkeypatch
):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-secret")
    client.cookies.set("ainulindale_home_session", "session-pending-123")

    # Mock token exchange
    mock_post = MagicMock()
    mock_post.status_code = 200
    mock_post.json.return_value = {"id_token": "fake-jwt"}
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_post
    mock_async_client.return_value.__aenter__.return_value = mock_client

    # Return a non-allowlisted email
    mock_id_token.verify_oauth2_token.return_value = {
        "nonce": "nonce-123",
        "sub": "sub-intruder",
        "email": "stranger@gmail.com",
        "name": "Random Person",
    }

    response = client.get(
        "/home/auth/google/callback?code=fake-code&state=state-123",
        follow_redirects=False,
    )

    # Must return 403 Forbidden with unauthorized friendly page
    assert response.status_code == 403
    assert "Access Restricted" in response.text
    assert "stranger@gmail.com" in response.text
    assert "Not on Allowlist" in response.text
    mock_home_db["delete_session"].assert_called_once_with("session-pending-123")


@patch("ainulindale_api.apps.home.auth.httpx.AsyncClient")
@patch("ainulindale_api.apps.home.auth.id_token")
@patch("ainulindale_api.apps.home.auth.google_requests.Request")
def test_home_callback_allowlisted_email_dana(
    mock_req, mock_id_token, mock_async_client, client, mock_home_db, monkeypatch
):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-secret")
    client.cookies.set("ainulindale_home_session", "session-pending-123")

    mock_post = MagicMock()
    mock_post.status_code = 200
    mock_post.json.return_value = {"id_token": "fake-jwt"}
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_post
    mock_async_client.return_value.__aenter__.return_value = mock_client

    # Allowlisted user
    mock_id_token.verify_oauth2_token.return_value = {
        "nonce": "nonce-123",
        "sub": "sub-dana",
        "email": "diederich@gmail.com",
        "name": "Dana M. Diederich",
    }

    auth_session = models.HomeSession(
        id="session-authenticated-456",
        user_id="user-123",
        email="diederich@gmail.com",
        name="Dana M. Diederich",
        is_authenticated=True,
    )
    mock_home_db["create_session"].return_value = auth_session

    response = client.get(
        "/home/auth/google/callback?code=fake-code&state=state-123",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/home/"
    assert "ainulindale_home_session" in response.cookies


@patch("ainulindale_api.apps.home.auth.httpx.AsyncClient")
@patch("ainulindale_api.apps.home.auth.id_token")
@patch("ainulindale_api.apps.home.auth.google_requests.Request")
def test_home_callback_allowlisted_email_michelle(
    mock_req, mock_id_token, mock_async_client, client, mock_home_db, monkeypatch
):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-secret")
    client.cookies.set("ainulindale_home_session", "session-pending-123")

    mock_post = MagicMock()
    mock_post.status_code = 200
    mock_post.json.return_value = {"id_token": "fake-jwt"}
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_post
    mock_async_client.return_value.__aenter__.return_value = mock_client

    # Allowlisted user: Michelle
    mock_id_token.verify_oauth2_token.return_value = {
        "nonce": "nonce-123",
        "sub": "sub-michelle",
        "email": "msdiederich@gmail.com",
        "name": "Michelle Diederich",
    }

    auth_session = models.HomeSession(
        id="session-authenticated-789",
        user_id="user-michelle",
        email="msdiederich@gmail.com",
        name="Michelle Diederich",
        is_authenticated=True,
    )
    mock_home_db["create_session"].return_value = auth_session

    response = client.get(
        "/home/auth/google/callback?code=fake-code&state=state-123",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/home/"
    assert "ainulindale_home_session" in response.cookies


def test_home_authenticated_success_page(
    client, mock_home_db, fake_authenticated_session
):
    client.cookies.set("ainulindale_home_session", "session-auth-123")
    mock_home_db["get_session"].return_value = fake_authenticated_session

    response = client.get("/home/")
    assert response.status_code == 200
    assert "Welcome Home" in response.text
    assert "diederich@gmail.com" in response.text
    assert "Authorized (Allowlisted)" in response.text


def test_home_signout(client, mock_home_db):
    client.cookies.set("ainulindale_home_session", "session-auth-123")
    response = client.post("/home/auth/signout", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/home/"
    mock_home_db["delete_session"].assert_called_once_with("session-auth-123")


def test_home_verify_endpoint(client, mock_home_db, fake_authenticated_session):
    # Unauthenticated
    client.cookies.clear()
    mock_home_db["get_session"].return_value = None
    res_unauth = client.get("/home/auth/verify")
    assert res_unauth.status_code == 401

    # Authenticated
    client.cookies.set("ainulindale_home_session", "session-auth-123")
    mock_home_db["get_session"].return_value = fake_authenticated_session
    res_auth = client.get("/home/auth/verify")
    assert res_auth.status_code == 200
    assert res_auth.json()["status"] == "authorized"
    assert res_auth.headers["x-forwarded-user"] == "diederich@gmail.com"

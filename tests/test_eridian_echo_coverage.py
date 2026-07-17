import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from ainulindale_api.apps.eridian_echo import models, service
from ainulindale_api.main import app

client = TestClient(app)


@pytest.fixture
def fake_session():
    return models.Session(
        id="session-123", principal_id="owner-123", state="state-123", nonce="nonce-123"
    )


@pytest.fixture
def mock_auth_db(fake_session):
    with (
        patch(
            "ainulindale_api.apps.eridian_echo.auth.models.get_session",
            new_callable=AsyncMock,
        ) as mock_get_session,
        patch(
            "ainulindale_api.apps.eridian_echo.auth.models.create_session",
            new_callable=AsyncMock,
        ) as mock_create_session,
        patch(
            "ainulindale_api.apps.eridian_echo.auth.models.update_session",
            new_callable=AsyncMock,
        ) as mock_update_session,
        patch(
            "ainulindale_api.apps.eridian_echo.auth.models.delete_session",
            new_callable=AsyncMock,
        ) as mock_delete_session,
        patch(
            "ainulindale_api.apps.eridian_echo.auth.models.get_user_by_sub",
            new_callable=AsyncMock,
        ) as mock_get_user,
        patch(
            "ainulindale_api.apps.eridian_echo.auth.models.create_user",
            new_callable=AsyncMock,
        ) as mock_create_user,
        patch(
            "ainulindale_api.apps.eridian_echo.auth.models.link_jobs_to_user",
            new_callable=AsyncMock,
        ) as mock_link,
    ):
        mock_get_session.return_value = fake_session
        mock_create_session.return_value = fake_session
        mock_get_user.return_value = models.User(
            google_sub="sub1", email="test@test.com", name="Test"
        )

        yield {
            "get_session": mock_get_session,
            "create_session": mock_create_session,
            "update_session": mock_update_session,
            "delete_session": mock_delete_session,
            "get_user_by_sub": mock_get_user,
            "create_user": mock_create_user,
            "link_jobs_to_user": mock_link,
        }


def test_google_login(mock_auth_db):
    response = client.get(
        "/api/v1/eridian-echo/auth/google/login", follow_redirects=False
    )
    assert response.status_code == 303
    assert (
        "https://accounts.google.com/o/oauth2/v2/auth" in response.headers["location"]
    )


def test_google_login_new_session(mock_auth_db):
    mock_auth_db["get_session"].return_value = None
    response = client.get(
        "/api/v1/eridian-echo/auth/google/login", follow_redirects=False
    )
    assert response.status_code == 303
    assert "eridian_echo_session" in response.cookies


@patch("ainulindale_api.apps.eridian_echo.auth.httpx.AsyncClient")
@patch("ainulindale_api.apps.eridian_echo.auth.id_token")
@patch("ainulindale_api.apps.eridian_echo.auth.google_requests.Request")
def test_google_callback(mock_req, mock_id_token, mock_async_client, mock_auth_db):
    client.cookies.set("eridian_echo_session", "session-123")

    mock_id_token.verify_oauth2_token.return_value = {
        "nonce": "nonce-123",
        "sub": "sub123",
        "email": "test@test.com",
        "name": "Test Name",
    }

    # Mock httpx post
    mock_post = MagicMock()
    mock_post.status_code = 200
    mock_post.json.return_value = {"id_token": "fake_jwt"}

    mock_client_instance = AsyncMock()
    mock_client_instance.post.return_value = mock_post
    # Mock context manager
    mock_async_client.return_value.__aenter__.return_value = mock_client_instance

    response = client.get(
        "/api/v1/eridian-echo/auth/google/callback?code=fakecode&state=state-123",
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "/api/v1/eridian-echo/" in response.headers["location"]


def test_signout(mock_auth_db):
    client.cookies.set("eridian_echo_session", "session-123")
    response = client.post(
        "/api/v1/eridian-echo/auth/signout", follow_redirects=False, json={}
    )
    assert response.status_code == 303
    mock_auth_db["delete_session"].assert_called_once_with("session-123")


# --- API tests ---
@pytest.fixture
def mock_api_db(fake_session):
    with (
        patch(
            "ainulindale_api.apps.eridian_echo.api.models.get_session",
            new_callable=AsyncMock,
        ) as mock_get_session,
        patch(
            "ainulindale_api.apps.eridian_echo.api.models.get_job",
            new_callable=AsyncMock,
        ) as mock_get_job,
        patch(
            "ainulindale_api.apps.eridian_echo.api.models.delete_job",
            new_callable=AsyncMock,
        ) as mock_delete_job,
    ):
        mock_get_session.return_value = fake_session
        fake_job = models.Job(
            **{"_id": "job-123", "owner_id": "owner-123", "filename": "test.mp3"}
        )
        mock_get_job.return_value = fake_job

        yield {
            "get_session": mock_get_session,
            "get_job": mock_get_job,
            "delete_job": mock_delete_job,
        }


def test_get_job(mock_api_db):
    client.cookies.set("eridian_echo_session", "session-123")
    response = client.get("/api/v1/eridian-echo/jobs/job-123")
    assert response.status_code == 200
    assert response.json()["id"] == "job-123"


def test_get_job_not_found(mock_api_db):
    client.cookies.set("eridian_echo_session", "session-123")
    mock_api_db["get_job"].return_value = None
    response = client.get("/api/v1/eridian-echo/jobs/job-123")
    assert response.status_code == 404


def test_delete_job(mock_api_db):
    client.cookies.set("eridian_echo_session", "session-123")
    response = client.delete("/api/v1/eridian-echo/jobs/job-123")
    assert response.status_code == 204
    mock_api_db["delete_job"].assert_called_once_with("job-123")


# --- Service tests ---
@patch("ainulindale_api.apps.eridian_echo.service.os.path.exists")
def test_get_client(mock_exists):
    # Just basic coverage
    mock_exists.return_value = False
    os.environ["GEMINI_API_KEY"] = "fake-key"
    client = service.get_client()
    assert client is not None
    # Reset singleton for tests
    service._client = None


@pytest.mark.anyio
@patch(
    "ainulindale_api.apps.eridian_echo.service.models.update_job_status",
    new_callable=AsyncMock,
)
@patch("ainulindale_api.apps.eridian_echo.service.get_client")
async def test_transcribe_mp3(mock_get_client, mock_update):
    mock_genai_client = MagicMock()
    mock_genai_client.files.upload.return_value = MagicMock(name="fake_file")
    mock_genai_client.models.generate_content.return_value = MagicMock(
        text="fake_transcript"
    )
    mock_get_client.return_value = mock_genai_client

    # create a dummy file
    with open("dummy.mp3", "w") as f:
        f.write("dummy")

    await service.transcribe_mp3("job-123", "dummy.mp3")

    # verify
    assert mock_update.call_count == 2
    mock_update.assert_any_call("job-123", "succeeded", transcript="fake_transcript")

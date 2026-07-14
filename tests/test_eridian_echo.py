import os
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from ainulindale_api.apps.eridian_echo import models
from ainulindale_api.main import app

client = TestClient(app)

# The user explicitly asked to run E2E Gemini tests using the provided context MP3.
MP3_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../context/new-service-test.mp3")
)


@pytest.fixture
def mock_db():
    with (
        patch(
            "ainulindale_api.apps.eridian_echo.api.models.create_job",
            new_callable=AsyncMock,
        ) as mock_create,
        patch(
            "ainulindale_api.apps.eridian_echo.api.models.get_job",
            new_callable=AsyncMock,
        ) as mock_get,
        patch(
            "ainulindale_api.apps.eridian_echo.api.models.get_jobs_for_owner",
            new_callable=AsyncMock,
        ) as mock_get_owner,
        patch(
            "ainulindale_api.apps.eridian_echo.service.models.update_job_status",
            new_callable=AsyncMock,
        ) as mock_update,
    ):
        # Create a fake job
        fake_job = models.Job(
            id="test-123", owner_id="owner-456", filename="new-service-test.mp3"
        )
        mock_create.return_value = fake_job
        mock_get.return_value = fake_job
        mock_get_owner.return_value = [fake_job]

        yield {
            "create_job": mock_create,
            "get_job": mock_get,
            "get_jobs_for_owner": mock_get_owner,
            "update_job_status": mock_update,
        }


def test_eridian_echo_frontend_sets_cookie() -> None:
    response = client.get("/api/v1/eridian-echo/")
    assert response.status_code == 200
    assert "eridian_echo_owner" in response.cookies


@pytest.mark.skipif(
    not os.path.exists(MP3_PATH) or not os.environ.get("GEMINI_API_KEY"),
    reason="Missing test MP3 or GEMINI_API_KEY environment variable"
)
def test_eridian_echo_e2e_gemini_transcription(mock_db) -> None:

    # First get the page to acquire a cookie
    client.get("/api/v1/eridian-echo/")
    cookie = client.cookies.get("eridian_echo_owner")
    assert cookie is not None

    # Now upload the file
    with open(MP3_PATH, "rb") as f:
        # Note: TestClient doesn't run background tasks by default
        # unless we wait for them,
        # or it runs them synchronously depending on FastAPI version.
        # FastAPI's TestClient runs background tasks after sending the response.
        response = client.post(
            "/api/v1/eridian-echo/upload",
            files={"file": ("new-service-test.mp3", f, "audio/mpeg")},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["filename"] == "new-service-test.mp3"

    # Verify DB was called
    mock_db["create_job"].assert_called_once()

    # Verify the background task executed and called Gemini
    # It updates the job status
    assert mock_db["update_job_status"].call_count >= 2

    # Find the call that set status="succeeded"
    success_call = None
    for call in mock_db["update_job_status"].call_args_list:
        args, kwargs = call
        if args[1] == "succeeded":
            success_call = kwargs
            break

    assert success_call is not None, "Job status was not updated to succeeded"
    transcript = success_call.get("transcript", "")
    assert len(transcript) > 0
    assert "Local Host" in transcript or "Remote Guest" in transcript


def test_jobs_list_requires_cookie(mock_db) -> None:
    # Clear cookies
    client.cookies.clear()

    # Request should return empty array if no cookie
    response = client.get("/api/v1/eridian-echo/jobs")
    assert response.status_code == 200
    assert response.json() == []

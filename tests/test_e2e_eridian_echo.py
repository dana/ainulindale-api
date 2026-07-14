import asyncio
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from motor.motor_asyncio import AsyncIOMotorClient

from ainulindale_api.core import db
from ainulindale_api.main import app

MP3_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "fixtures/new-service-test.mp3")
)


@pytest.fixture(scope="function")
def unique_db_name():
    return f"test_e2e_db_{uuid.uuid4().hex}"


@pytest.fixture(scope="function")
def setup_teardown_db(unique_db_name):
    # Setup
    original_db_name = db.DATABASE_NAME
    original_mongo_uri = db.MONGO_URI

    db.DATABASE_NAME = unique_db_name
    db.MONGO_URI = "mongodb://127.0.0.1:27017"

    yield unique_db_name

    # Teardown
    db.DATABASE_NAME = original_db_name
    db.MONGO_URI = original_mongo_uri

    # Drop the test database synchronously wrapping async call
    async def drop_db():
        client = AsyncIOMotorClient("mongodb://127.0.0.1:27017")
        await client.drop_database(unique_db_name)
        client.close()

    asyncio.run(drop_db())


@pytest.mark.skipif(
    not os.path.exists(MP3_PATH) or not os.environ.get("GEMINI_API_KEY"),
    reason="Missing test MP3 or GEMINI_API_KEY environment variable",
)
def test_eridian_echo_e2e_real_transcription(setup_teardown_db):
    # Using 'with' on TestClient triggers FastAPI lifespan (startup/shutdown events)
    with TestClient(app) as client:
        # First get the page to acquire a cookie
        client.get("/api/v1/eridian-echo/")
        cookie = client.cookies.get("eridian_echo_owner")
        assert cookie is not None

        # Now upload the file
        with open(MP3_PATH, "rb") as f:
            # TestClient runs background tasks after sending the response
            # Since our transcribe task uses asyncio.to_thread, it will block
            # the TestClient until completion
            response = client.post(
                "/api/v1/eridian-echo/upload",
                files={"file": ("new-service-test.mp3", f, "audio/mpeg")},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["filename"] == "new-service-test.mp3"
        job_id = data["id"]

        # Verify the job is in the list and succeeded
        response = client.get("/api/v1/eridian-echo/jobs")
        assert response.status_code == 200
        jobs = response.json()
        assert len(jobs) > 0
        job = next((j for j in jobs if j["id"] == job_id), None)
        assert job is not None
        assert job["status"] == "succeeded"

        transcript = job.get("transcript", "")
        assert transcript is not None
        transcript_lower = transcript.lower()

        # The transcription should include something like
        # "Hello, this is a test of the new service."
        # We check for general keywords that prove the
        # specific test file was transcribed correctly.
        assert "hello" in transcript_lower or "test" in transcript_lower
        assert "new service" in transcript_lower or "test" in transcript_lower

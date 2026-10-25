from __future__ import annotations

from unittest.mock import AsyncMock, patch

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
        id="session-dana-common",
        user_id="user-dana",
        email="diederich@gmail.com",
        name="Dana M. Diederich",
        is_authenticated=True,
    )


@pytest.fixture
def non_allowlisted_session():
    return models.HomeSession(
        id="session-stranger",
        user_id="user-stranger",
        email="stranger@example.com",
        name="Unauthorized User",
        is_authenticated=True,
    )


@pytest.fixture
def test_common_dir(tmp_path, monkeypatch):
    test_dir = tmp_path / "home-common"
    test_dir.mkdir()
    secret_file = test_dir / "test-sensitive-file.txt"
    secret_file.write_text("SENSITIVE_FLEET_DATA_SECRET_12345")

    nested_dir = test_dir / "nested"
    nested_dir.mkdir()
    nested_file = nested_dir / "nested-secret.txt"
    nested_file.write_text("NESTED_SENSITIVE_DATA")

    monkeypatch.setenv("HOME_COMMON_DIR", str(test_dir))
    return test_dir


@pytest.fixture
def mock_common_db():
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


def test_home_common_unauthenticated_file_inaccessible(
    client, mock_common_db, test_common_dir
):
    client.cookies.clear()
    mock_common_db["get_session"].return_value = None

    # Accessing directory unauthenticated redirects to login
    res_dir = client.get("/home/common", follow_redirects=False)
    assert res_dir.status_code == 303
    assert res_dir.headers["location"] == "/home/auth/google/login"

    # Accessing sensitive file unauthenticated redirects to login
    res_file = client.get(
        "/home/common/test-sensitive-file.txt", follow_redirects=False
    )
    assert res_file.status_code == 303
    assert res_file.headers["location"] == "/home/auth/google/login"

    # Verify secret content is NEVER leaked in response
    assert "SENSITIVE_FLEET_DATA_SECRET_12345" not in res_file.text

    # Accessing via JSON accept header returns 401 Unauthorized
    res_api = client.get(
        "/home/common/test-sensitive-file.txt",
        headers={"Accept": "application/json"},
    )
    assert res_api.status_code == 401
    assert res_api.json()["detail"] == "Authentication required"
    assert "SENSITIVE_FLEET_DATA_SECRET_12345" not in res_api.text


def test_home_common_non_allowlisted_email_forbidden(
    client, mock_common_db, test_common_dir, non_allowlisted_session
):
    client.cookies.set("ainulindale_home_session", "session-stranger")
    mock_common_db["get_session"].return_value = non_allowlisted_session

    res = client.get("/home/common/test-sensitive-file.txt")
    assert res.status_code == 403
    assert "Access Restricted" in res.text
    assert "SENSITIVE_FLEET_DATA_SECRET_12345" not in res.text


def test_home_common_allowlisted_user_can_browse_and_download(
    client, mock_common_db, test_common_dir, allowlisted_session
):
    client.cookies.set("ainulindale_home_session", "session-dana-common")
    mock_common_db["get_session"].return_value = allowlisted_session

    # 1. Directory listing
    res_list = client.get("/home/common/")
    assert res_list.status_code == 200
    assert "home-common" in res_list.text
    assert "test-sensitive-file.txt" in res_list.text
    assert "nested" in res_list.text

    # 2. File download
    res_file = client.get("/home/common/test-sensitive-file.txt")
    assert res_file.status_code == 200
    assert res_file.text == "SENSITIVE_FLEET_DATA_SECRET_12345"

    # 3. Nested file download
    res_nested = client.get("/home/common/nested/nested-secret.txt")
    assert res_nested.status_code == 200
    assert res_nested.text == "NESTED_SENSITIVE_DATA"


def test_home_common_path_traversal_blocked(
    client, mock_common_db, test_common_dir, allowlisted_session
):
    client.cookies.set("ainulindale_home_session", "session-dana-common")
    mock_common_db["get_session"].return_value = allowlisted_session

    res = client.get("/home/common/../../../../etc/passwd")
    assert res.status_code == 404


def test_home_common_missing_file_returns_404(
    client, mock_common_db, test_common_dir, allowlisted_session
):
    client.cookies.set("ainulindale_home_session", "session-dana-common")
    mock_common_db["get_session"].return_value = allowlisted_session

    res = client.get("/home/common/nonexistent-file.txt")
    assert res.status_code == 404

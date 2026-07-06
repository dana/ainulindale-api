from __future__ import annotations

from fastapi.testclient import TestClient

from ainulindale_api.main import app

client = TestClient(app)


def assert_json_response(response) -> dict:
    content_type = response.headers.get("content-type", "")
    assert content_type.startswith("application/json")
    return response.json()


def test_app_imports_and_has_title() -> None:
    assert app.title == "Ainulindale API"


def test_healthz_returns_json() -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert assert_json_response(response) == {"status": "ok"}


def test_readyz_returns_json() -> None:
    response = client.get("/readyz")

    assert response.status_code == 200
    assert assert_json_response(response) == {"status": "ready"}


def test_public_endpoint_accepts_json_and_returns_json() -> None:
    response = client.post("/api/v1/echo", json={"message": "hello"})

    assert response.status_code == 200
    assert assert_json_response(response) == {"message": "hello", "length": 5}


def test_public_endpoint_accepts_json_with_charset() -> None:
    response = client.post(
        "/api/v1/echo",
        content='{"message":"hello"}',
        headers={"Content-Type": "application/json; charset=utf-8"},
    )

    assert response.status_code == 200
    assert assert_json_response(response) == {"message": "hello", "length": 5}


def test_public_endpoint_rejects_invalid_json_with_json_error() -> None:
    response = client.post(
        "/api/v1/echo",
        content='{"message":',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    body = assert_json_response(response)
    assert "detail" in body


def test_public_endpoint_rejects_missing_content_type_with_json_error() -> None:
    response = client.post(
        "/api/v1/echo",
        content='{"message":"hello"}',
    )

    assert response.status_code == 415
    assert_json_response(response)


def test_public_endpoint_rejects_wrong_content_type_with_json_error() -> None:
    response = client.post(
        "/api/v1/echo",
        content='{"message":"hello"}',
        headers={"Content-Type": "text/plain"},
    )

    assert response.status_code == 415
    assert_json_response(response)


def test_public_endpoint_validation_errors_are_json() -> None:
    response = client.post("/api/v1/echo", json={"message": ""})

    assert response.status_code == 422
    body = assert_json_response(response)
    assert "detail" in body


def test_public_endpoint_rejects_unexpected_fields() -> None:
    response = client.post(
        "/api/v1/echo",
        json={"message": "hello", "unexpected": True},
    )

    assert response.status_code == 422
    body = assert_json_response(response)
    assert "detail" in body


def test_404_is_json_not_html() -> None:
    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    body = assert_json_response(response)
    assert body == {"detail": "Not Found"}


def test_root_path_is_not_accidentally_available() -> None:
    response = client.get("/")

    assert response.status_code == 404
    assert_json_response(response)


def test_docs_and_redoc_are_not_enabled() -> None:
    docs_response = client.get("/docs")
    redoc_response = client.get("/redoc")

    assert docs_response.status_code == 404
    assert redoc_response.status_code == 404
    assert_json_response(docs_response)
    assert_json_response(redoc_response)


def test_openapi_advertises_only_intended_paths() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = assert_json_response(response)

    assert set(schema["paths"].keys()) == {
        "/healthz",
        "/readyz",
        "/api/v1/echo",
        "/api/v1/happy-path",
    }
    assert set(schema["paths"]["/api/v1/echo"].keys()) == {"post"}
    assert set(schema["paths"]["/api/v1/happy-path"].keys()) == {"post"}
    assert "/" not in schema["paths"]
    assert "/api" not in schema["paths"]
    assert "/api/v1" not in schema["paths"]
    assert "/docs" not in schema["paths"]
    assert "/redoc" not in schema["paths"]


def test_happy_path_endpoint_accepts_json_and_returns_json() -> None:
    response = client.post("/api/v1/happy-path", json={"message": "chunk 11"})

    assert response.status_code == 200
    assert assert_json_response(response) == {
        "message": "chunk 11",
        "proof": "chunk-11-happy-path",
        "length": 8,
    }


def test_happy_path_endpoint_rejects_missing_content_type_with_json_error() -> None:
    response = client.post(
        "/api/v1/happy-path",
        content='{"message":"chunk 11"}',
    )

    assert response.status_code == 415
    assert_json_response(response)


def test_happy_path_endpoint_rejects_wrong_content_type_with_json_error() -> None:
    response = client.post(
        "/api/v1/happy-path",
        content='{"message":"chunk 11"}',
        headers={"Content-Type": "text/plain"},
    )

    assert response.status_code == 415
    assert_json_response(response)


def test_happy_path_endpoint_rejects_invalid_json_with_json_error() -> None:
    response = client.post(
        "/api/v1/happy-path",
        content='{"message":',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    body = assert_json_response(response)
    assert "detail" in body


def test_happy_path_endpoint_rejects_empty_message() -> None:
    response = client.post("/api/v1/happy-path", json={"message": ""})

    assert response.status_code == 422
    body = assert_json_response(response)
    assert "detail" in body


def test_happy_path_endpoint_rejects_unexpected_fields() -> None:
    response = client.post(
        "/api/v1/happy-path",
        json={"message": "chunk 11", "unexpected": True},
    )

    assert response.status_code == 422
    body = assert_json_response(response)
    assert "detail" in body

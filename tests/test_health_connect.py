import gzip
import json
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from ainulindale_api.apps.health_connect.config import AUTH_TOKEN, DANA_SIGNATURES
from ainulindale_api.main import app

client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_connect_status_unauthorized() -> None:
    response = client.get("/api/v1/health-connect/status")
    assert response.status_code == 401


def test_health_connect_status_invalid_token() -> None:
    response = client.get(
        "/api/v1/health-connect/status",
        headers={"Authorization": "Bearer bad-token"},
    )
    assert response.status_code == 401


def test_health_connect_status_authorized(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "ainulindale_api.apps.health_connect.router.ARCHIVE_DIR", tmp_path
    )
    response = client.get(
        "/api/v1/health-connect/status",
        headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["archiveFilesCount"] == 0


def test_health_connect_import_dana_data(tmp_path: Path, monkeypatch) -> None:
    incoming = tmp_path / "incoming"
    archive = tmp_path / "archive"
    monkeypatch.setattr(
        "ainulindale_api.apps.health_connect.router.INCOMING_DIR", incoming
    )
    monkeypatch.setattr(
        "ainulindale_api.apps.health_connect.router.ARCHIVE_DIR", archive
    )
    monkeypatch.setattr(
        "ainulindale_api.apps.health_connect.receiver.ARCHIVE_DIR", archive
    )

    # Construct sample record with Dana's signature
    known_sig = next(iter(DANA_SIGNATURES))
    sample_records = [
        {
            "exportSchemaVersion": 1,
            "recordType": "StepsRecord",
            "source": {
                "packageName": known_sig,
                "dataOrigin": known_sig,
                "device": {"model": "Pixel 10", "manufacturer": "Google"},
            },
            "metadata": {"dataOrigin": known_sig},
            "record": {
                "startTime": "2026-11-09T08:00:00Z",
                "endTime": "2026-11-09T08:15:00Z",
                "count": 120,
            },
        }
    ]
    ndjson = "\n".join(json.dumps(r) for r in sample_records) + "\n"
    gzipped = gzip.compress(ndjson.encode("utf-8"))

    with patch(
        "ainulindale_api.apps.health_connect.receiver.send_unknown_signature_alert"
    ) as mock_alert:
        response = client.post(
            "/api/v1/health-connect/import",
            content=gzipped,
            headers={
                "Authorization": f"Bearer {AUTH_TOKEN}",
                "Content-Encoding": "gzip",
                "Content-Type": "application/x-ndjson",
            },
        )
        assert response.status_code == 200
        receipt = response.json()
        assert receipt["status"] == "ok"
        assert receipt["records"] == 1
        assert receipt["user"] == "dana"
        assert "receiptId" in receipt
        assert not mock_alert.called

    # Verify inventory counts
    inv_resp = client.get(
        "/api/v1/health-connect/inventory",
        headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
    )
    assert inv_resp.status_code == 200
    inv = inv_resp.json()
    assert inv["totalRecords"] == 1
    assert inv["users"] == {"dana": 1}
    assert inv["recordTypes"] == {"StepsRecord": 1}


def test_health_connect_import_unknown_signature_triggers_alert(
    tmp_path: Path, monkeypatch
) -> None:
    incoming = tmp_path / "incoming"
    archive = tmp_path / "archive"
    monkeypatch.setattr(
        "ainulindale_api.apps.health_connect.router.INCOMING_DIR", incoming
    )
    monkeypatch.setattr(
        "ainulindale_api.apps.health_connect.router.ARCHIVE_DIR", archive
    )
    monkeypatch.setattr(
        "ainulindale_api.apps.health_connect.receiver.ARCHIVE_DIR", archive
    )

    unknown_sig = "com.android.healthconnect.phone.junknownsignature999"
    sample_records = [
        {
            "exportSchemaVersion": 1,
            "recordType": "HeartRateRecord",
            "source": {
                "packageName": unknown_sig,
                "dataOrigin": unknown_sig,
                "device": {"model": "Galaxy S25", "manufacturer": "Samsung"},
            },
            "metadata": {"dataOrigin": unknown_sig},
            "record": {
                "startTime": "2026-11-09T08:00:00Z",
                "bpm": 72,
            },
        }
    ]
    ndjson = "\n".join(json.dumps(r) for r in sample_records) + "\n"
    gzipped = gzip.compress(ndjson.encode("utf-8"))

    with patch(
        "ainulindale_api.apps.health_connect.receiver.send_unknown_signature_alert"
    ) as mock_alert:
        response = client.post(
            "/api/v1/health-connect/import",
            content=gzipped,
            headers={
                "Authorization": f"Bearer {AUTH_TOKEN}",
                "Content-Encoding": "gzip",
                "Content-Type": "application/x-ndjson",
            },
        )
        assert response.status_code == 200
        receipt = response.json()
        assert receipt["status"] == "ok"
        assert receipt["records"] == 1
        assert receipt["user"] == "unknown"
        assert mock_alert.called
        call_kwargs = mock_alert.call_args[1]
        assert unknown_sig in call_kwargs["signatures"]


def test_health_connect_import_empty_rejected(tmp_path: Path, monkeypatch) -> None:
    incoming = tmp_path / "incoming"
    archive = tmp_path / "archive"
    monkeypatch.setattr(
        "ainulindale_api.apps.health_connect.router.INCOMING_DIR", incoming
    )
    monkeypatch.setattr(
        "ainulindale_api.apps.health_connect.router.ARCHIVE_DIR", archive
    )

    response = client.post(
        "/api/v1/health-connect/import",
        content=b"",
        headers={
            "Authorization": f"Bearer {AUTH_TOKEN}",
            "Content-Type": "application/x-ndjson",
        },
    )
    assert response.status_code == 400

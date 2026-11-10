from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ainulindale_api.apps.health_connect.config import (
    ARCHIVE_DIR,
    DANA_SIGNATURES,
    MICHELLE_SIGNATURES,
)
from ainulindale_api.apps.health_connect.ntfy import send_unknown_signature_alert

logger = logging.getLogger("health_connect.receiver")


class ProcessResult:
    def __init__(
        self,
        receipt_id: str,
        received_at: str,
        bytes_stored: int,
        sha256_hash: str,
        record_count: int,
        archive_path: Path,
        meta_path: Path,
        type_counts: dict[str, int],
        origin_counts: dict[str, int],
        signatures: set[str],
        device_models: set[str],
        user: str,
        min_time: str | None,
        max_time: str | None,
    ):
        self.receipt_id = receipt_id
        self.received_at = received_at
        self.bytes_stored = bytes_stored
        self.sha256 = sha256_hash
        self.records = record_count
        self.archive_path = archive_path
        self.meta_path = meta_path
        self.type_counts = type_counts
        self.origin_counts = origin_counts
        self.signatures = signatures
        self.device_models = device_models
        self.user = user
        self.min_time = min_time
        self.max_time = max_time

    def to_receipt_dict(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "receivedAt": self.received_at,
            "bytes": self.bytes_stored,
            "sha256": self.sha256,
            "records": self.records,
            "receiptId": self.receipt_id,
            "user": self.user,
        }

    def to_meta_dict(self, client_ip: str | None = None) -> dict[str, Any]:
        d = self.to_receipt_dict()
        d.update(
            {
                "archiveFile": str(self.archive_path.name),
                "recordTypeCounts": self.type_counts,
                "originCounts": self.origin_counts,
                "signatures": sorted(self.signatures),
                "deviceModels": sorted(self.device_models),
                "user": self.user,
                "minTime": self.min_time,
                "maxTime": self.max_time,
                "clientIp": client_ip,
            }
        )
        return d


def is_gzip(data_head: bytes) -> bool:
    return len(data_head) >= 2 and data_head[0] == 0x1F and data_head[1] == 0x8B


def process_upload(
    temp_file_path: Path,
    client_ip: str | None = None,
    archive_base_dir: Path = ARCHIVE_DIR,
) -> ProcessResult:
    receipt_id = str(uuid.uuid4())
    now = datetime.now(UTC).astimezone()
    iso_now = now.isoformat()

    with open(temp_file_path, "rb") as f:
        head = f.read(2)

    already_gzipped = is_gzip(head)

    type_counts: dict[str, int] = {}
    origin_counts: dict[str, int] = {}
    signatures: set[str] = set()
    device_models: set[str] = set()
    min_time: str | None = None
    max_time: str | None = None
    record_count = 0

    def inspect_record(obj: dict[str, Any]) -> None:
        nonlocal record_count, min_time, max_time
        record_count += 1

        rec_type = obj.get("recordType") or obj.get("type") or "UnknownRecord"
        type_counts[rec_type] = type_counts.get(rec_type, 0) + 1

        source = obj.get("source")
        origin = None
        if isinstance(source, dict):
            origin = source.get("packageName") or source.get("dataOrigin")
            dev = source.get("device")
            if isinstance(dev, dict):
                model = dev.get("model")
                if model:
                    device_models.add(str(model))

        if not origin and "metadata" in obj and isinstance(obj["metadata"], dict):
            origin = obj["metadata"].get("dataOrigin")

        if not origin:
            origin = obj.get("dataOrigin") or "unknown"
        origin_counts[origin] = origin_counts.get(origin, 0) + 1

        # Check for package instance signatures (healthconnect.phone.*)
        for cand in (
            origin,
            source.get("packageName") if isinstance(source, dict) else None,
            source.get("dataOrigin") if isinstance(source, dict) else None,
            obj.get("metadata", {}).get("dataOrigin")
            if isinstance(obj.get("metadata"), dict)
            else None,
        ):
            if cand and isinstance(cand, str) and "healthconnect.phone." in cand:
                signatures.add(cand)

        rec = obj.get("record") if isinstance(obj.get("record"), dict) else obj
        t = rec.get("startTime") or rec.get("time")
        if t and isinstance(t, str):
            if min_time is None or t < min_time:
                min_time = t
            if max_time is None or t > max_time:
                max_time = t

    if already_gzipped:
        with gzip.open(temp_file_path, "rt", encoding="utf-8", errors="replace") as gz:
            for line_no, line in enumerate(gz, start=1):
                s = line.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                except Exception as e:
                    raise ValueError(f"Invalid JSON on line {line_no}: {e}") from e
                if not isinstance(obj, dict):
                    raise ValueError(f"Line {line_no} is not a JSON object")
                inspect_record(obj)
    else:
        temp_gz_path = temp_file_path.with_suffix(".gz.tmp")
        with (
            open(temp_file_path, encoding="utf-8", errors="replace") as fin,
            gzip.open(temp_gz_path, "wt", encoding="utf-8") as gout,
        ):
            for line_no, line in enumerate(fin, start=1):
                s = line.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                except Exception as e:
                    temp_gz_path.unlink(missing_ok=True)
                    raise ValueError(f"Invalid JSON on line {line_no}: {e}") from e
                if not isinstance(obj, dict):
                    temp_gz_path.unlink(missing_ok=True)
                    raise ValueError(f"Line {line_no} is not a JSON object")
                inspect_record(obj)
                gout.write(s + "\n")
        temp_file_path.unlink(missing_ok=True)
        temp_file_path = temp_gz_path

    if record_count == 0:
        temp_file_path.unlink(missing_ok=True)
        raise ValueError("NDJSON payload contains 0 records")

    # Determine user identity from signatures
    user = "unknown"
    if signatures:
        if any(s in DANA_SIGNATURES for s in signatures):
            user = "dana"
        elif any(s in MICHELLE_SIGNATURES for s in signatures):
            user = "michelle"
        else:
            logger.warning(
                "Unrecognized signatures detected: %s. Dispatching ntfy alert.",
                signatures,
            )
            send_unknown_signature_alert(
                signatures=signatures,
                client_ip=client_ip,
                record_count=record_count,
                receipt_id=receipt_id,
                device_models=device_models,
                record_types=type_counts,
            )
    else:
        logger.warning(
            "No Health Connect signature found in export (%d records). Alerting.",
            record_count,
        )
        send_unknown_signature_alert(
            signatures=signatures,
            client_ip=client_ip,
            record_count=record_count,
            receipt_id=receipt_id,
            device_models=device_models,
            record_types=type_counts,
        )

    # Compute SHA-256 and byte size
    hasher = hashlib.sha256()
    bytes_stored = 0
    with open(temp_file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
            bytes_stored += len(chunk)
    sha256_hash = hasher.hexdigest()

    # Destination directory: archive/YYYY/MM/YYYY-MM-DD/
    year_str = now.strftime("%Y")
    month_str = now.strftime("%m")
    day_str = now.strftime("%Y-%m-%d")
    target_dir = archive_base_dir / year_str / month_str / day_str
    target_dir.mkdir(parents=True, exist_ok=True)

    time_prefix = now.strftime("%Y-%m-%dT%H-%M-%S.%f%z")
    archive_file = target_dir / f"{time_prefix}_{receipt_id}.ndjson.gz"
    meta_file = target_dir / f"{time_prefix}_{receipt_id}.meta.json"

    # Atomic move
    os.replace(temp_file_path, archive_file)

    res = ProcessResult(
        receipt_id=receipt_id,
        received_at=iso_now,
        bytes_stored=bytes_stored,
        sha256_hash=sha256_hash,
        record_count=record_count,
        archive_path=archive_file,
        meta_path=meta_file,
        type_counts=type_counts,
        origin_counts=origin_counts,
        signatures=signatures,
        device_models=device_models,
        user=user,
        min_time=min_time,
        max_time=max_time,
    )

    meta_content = json.dumps(res.to_meta_dict(client_ip=client_ip), indent=2)
    meta_file.write_text(meta_content, encoding="utf-8")

    return res

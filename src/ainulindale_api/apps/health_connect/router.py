from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse

from ainulindale_api.apps.health_connect.config import (
    ARCHIVE_DIR,
    AUTH_TOKEN,
    INCOMING_DIR,
    MAX_BODY_SIZE,
)
from ainulindale_api.apps.health_connect.receiver import process_upload

logger = logging.getLogger("health_connect.api")

router = APIRouter(tags=["health-connect"])


def verify_bearer_token(authorization: str | None = Header(None)) -> str:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format. Expected 'Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = parts[1]
    if token != AUTH_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


@router.get("/status")
def get_status(_token: str = Depends(verify_bearer_token)) -> dict[str, Any]:
    meta_files = list(ARCHIVE_DIR.glob("**/*.meta.json"))
    total_bytes = 0
    total_records = 0
    latest_meta = None
    latest_time = ""

    for mf in meta_files:
        try:
            data = json.loads(mf.read_text(encoding="utf-8"))
            total_records += data.get("records", 0)
            total_bytes += data.get("bytes", 0)
            recv = data.get("receivedAt", "")
            if recv > latest_time:
                latest_time = recv
                latest_meta = data
        except Exception:
            pass

    return {
        "status": "ok",
        "archivePath": str(ARCHIVE_DIR),
        "archiveFilesCount": len(meta_files),
        "totalBytesStored": total_bytes,
        "totalRecordsStored": total_records,
        "latestUpload": latest_meta,
    }


@router.get("/inventory")
def get_inventory(_token: str = Depends(verify_bearer_token)) -> dict[str, Any]:
    meta_files = list(ARCHIVE_DIR.glob("**/*.meta.json"))
    type_totals: dict[str, int] = {}
    origin_totals: dict[str, int] = {}
    user_totals: dict[str, int] = {}
    earliest_time: str | None = None
    latest_time: str | None = None
    total_records = 0

    for mf in sorted(meta_files):
        try:
            data = json.loads(mf.read_text(encoding="utf-8"))
            records = data.get("records", 0)
            total_records += records

            user = data.get("user", "unknown")
            user_totals[user] = user_totals.get(user, 0) + records

            for t, count in data.get("recordTypeCounts", {}).items():
                type_totals[t] = type_totals.get(t, 0) + count

            for o, count in data.get("originCounts", {}).items():
                origin_totals[o] = origin_totals.get(o, 0) + count

            min_t = data.get("minTime")
            if min_t and (earliest_time is None or min_t < earliest_time):
                earliest_time = min_t
            max_t = data.get("maxTime")
            if max_t and (latest_time is None or max_t > latest_time):
                latest_time = max_t
        except Exception:
            continue

    return {
        "totalUploadBatches": len(meta_files),
        "totalRecords": total_records,
        "users": user_totals,
        "recordTypes": type_totals,
        "origins": origin_totals,
        "earliestRecordTime": earliest_time,
        "latestRecordTime": latest_time,
    }


@router.post("/import")
async def import_health_data(
    request: Request,
    _token: str = Depends(verify_bearer_token),
) -> JSONResponse:
    INCOMING_DIR.mkdir(parents=True, exist_ok=True)
    upload_id = str(uuid.uuid4())
    temp_path = INCOMING_DIR / f"upload_{upload_id}.tmp"

    bytes_read = 0
    try:
        with open(temp_path, "wb") as f:
            async for chunk in request.stream():
                bytes_read += len(chunk)
                if bytes_read > MAX_BODY_SIZE:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=(
                            "Payload exceeds maximum allowed size "
                            f"({MAX_BODY_SIZE} bytes)"
                        ),
                    )
                f.write(chunk)

        if bytes_read == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Empty request body",
            )

        client_ip = request.client.host if request.client else None
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()

        result = process_upload(
            temp_path,
            client_ip=client_ip,
            archive_base_dir=ARCHIVE_DIR,
        )

        logger.info(
            "Health Connect import: user=%s, receipt=%s, records=%d, bytes=%d",
            result.user,
            result.receipt_id,
            result.records,
            result.bytes_stored,
        )

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=result.to_receipt_dict(),
        )

    except HTTPException:
        temp_path.unlink(missing_ok=True)
        raise
    except ValueError as e:
        temp_path.unlink(missing_ok=True)
        logger.warning("Import validation rejected: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Validation error: {e}",
        ) from e
    except Exception as e:
        temp_path.unlink(missing_ok=True)
        logger.exception("Internal error processing upload")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal processing error: {e}",
        ) from e

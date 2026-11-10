from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from ainulindale_api.apps.health_connect.config import NTFY_TOPIC, NTFY_URL

logger = logging.getLogger("health_connect.ntfy")


def send_unknown_signature_alert(
    signatures: set[str],
    client_ip: str | None,
    record_count: int,
    receipt_id: str,
    device_models: set[str],
    record_types: dict[str, int],
) -> bool:
    """Send an urgent Priority 5 alert to Dana's ntfy topic when an unrecognized

    Health Connect Package Instance Signature arrives.
    """
    if not NTFY_TOPIC:
        logger.warning("No NTFY_TOPIC configured; skipping signature alert")
        return False

    sig_list = (
        ", ".join(f"`{s}`" for s in sorted(signatures))
        if signatures
        else "*None detected*"
    )
    dev_list = (
        ", ".join(f"`{d}`" for d in sorted(device_models))
        if device_models
        else "Unknown"
    )
    types_summary = ", ".join(f"{k}: {v}" for k, v in sorted(record_types.items())[:5])

    lines = [
        "### 🚨 Unrecognized Health Connect Device Signature",
        "",
        (
            "A Health Connect telemetry export was received with an "
            "**unknown Package Instance Signature**."
        ),
        "",
        f"- **Signatures**: {sig_list}",
        f"- **Device Model**: {dev_list}",
        f"- **Client IP**: `{client_ip or 'unknown'}`",
        f"- **Total Records**: `{record_count}`",
        f"- **Receipt ID**: `{receipt_id}`",
        f"- **Sample Record Types**: {types_summary}",
        "",
        (
            "**Action Required**: If this is Michelle's phone or a new device, "
            "add this signature to the recognized roster. "
            "If unexpected, investigate immediately."
        ),
    ]
    message = "\n".join(lines)

    payload: dict[str, Any] = {
        "topic": NTFY_TOPIC,
        "title": "⚠️ Security Alert: Unknown Health Connect Device",
        "message": message,
        "priority": 5,
        "tags": ["warning", "rotating_light"],
        "markdown": True,
    }

    url = f"{NTFY_URL.rstrip('/')}/{NTFY_TOPIC}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310 # noqa: S310
            logger.info("Sent unknown signature ntfy alert (HTTP %d)", resp.status)
            return True
    except Exception as e:
        logger.error("Failed to send unknown signature ntfy alert: %s", e)
        return False

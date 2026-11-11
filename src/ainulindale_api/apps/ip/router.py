from __future__ import annotations

import ipaddress
import os
import re

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["client-ip"])

templates_dir = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=templates_dir)

CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
    "X-Content-Type-Options": "nosniff",
}

CLI_INDICATORS = (
    "curl/",
    "wget/",
    "httpie",
    "python-requests",
    "aiohttp",
    "go-http-client",
)


def _sanitize_and_validate_ip(raw: str) -> tuple[str, str] | None:
    """Sanitize and validate an IP string, returning (ip, 'IPv4'|'IPv6') or None."""
    raw = raw.strip()
    if not raw:
        return None

    # Handle bracketed IPv6: [2001:db8::1] or [2001:db8::1]:port
    bracket_match = re.match(r"^\[([a-fA-F0-9:]+)\](?::\d+)?$", raw)
    if bracket_match:
        raw_ip = bracket_match.group(1)
    elif ":" in raw and "." in raw:
        # IPv4 with port: 192.0.2.1:12345
        raw_ip = raw.split(":", 1)[0]
    elif raw.count(":") == 1 and "." not in raw:
        # Host:port where host is not IPv6
        raw_ip = raw.split(":", 1)[0]
    else:
        # Standard IPv4 or plain IPv6 (e.g. 2001:db8::1)
        raw_ip = raw

    try:
        ip_obj = ipaddress.ip_address(raw_ip)
        version = f"IPv{ip_obj.version}"
        return str(ip_obj), version
    except ValueError:
        return None


def extract_client_ip(request: Request) -> tuple[str, str]:
    """
    Extract the client's public or incoming IP address from request headers
    or direct connection, and determine its IP version (IPv4 or IPv6).

    Returns a tuple of (ip_address_string, version_string e.g. 'IPv4' or 'IPv6').
    """
    candidates: list[str] = []

    # X-Forwarded-For: client, proxy1, proxy2
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        for part in forwarded.split(","):
            cleaned = part.strip()
            if cleaned:
                candidates.append(cleaned)

    # Direct proxy headers
    for header in ("x-real-ip", "cf-connecting-ip", "true-client-ip"):
        val = request.headers.get(header)
        if val and val.strip():
            candidates.append(val.strip())

    # Direct client connection
    if request.client and request.client.host:
        candidates.append(request.client.host.strip())

    for raw in candidates:
        parsed = _sanitize_and_validate_ip(raw)
        if parsed:
            return parsed

    return "127.0.0.1", "IPv4"


def should_render_json(request: Request) -> bool:
    """Check if the client requested JSON output."""
    fmt = request.query_params.get("format", "").lower()
    if fmt == "json" or "json" in request.query_params:
        return True
    accept = request.headers.get("accept", "").lower()
    return "application/json" in accept and "text/html" not in accept


def should_render_html(request: Request) -> bool:
    """
    Determine whether to return an HTML page or plain text.
    Web browsers typically send 'Accept: text/html,...'.
    Command line tools (curl, wget, httpie) send '*/*' or 'text/plain'.
    """
    accept = request.headers.get("accept", "").lower()
    user_agent = request.headers.get("user-agent", "").lower()

    # Explicit format overrides
    if "format" in request.query_params:
        fmt = request.query_params["format"].lower()
        if fmt in ("html", "web"):
            return True
        if fmt in ("text", "txt", "plain", "raw"):
            return False

    # CLI tools default to plain text unless explicitly requesting html
    is_cli = any(
        user_agent.startswith(cli) or f" {cli}" in user_agent for cli in CLI_INDICATORS
    )
    if is_cli:
        return "text/html" in accept and not accept.startswith("*/*")

    # If client accepts text/html, render HTML
    return "text/html" in accept


@router.get("/ip", include_in_schema=False)
@router.get("/ip/", include_in_schema=False)
@router.get("/myip", include_in_schema=False)
@router.get("/myip/", include_in_schema=False)
async def get_client_ip(request: Request) -> Response:
    """Return client IP as plain text (with newline) or HTML for browsers."""
    ip, version = extract_client_ip(request)

    if should_render_json(request):
        return JSONResponse(
            status_code=200,
            content={"ip": ip, "version": version},
            headers=CACHE_HEADERS,
        )

    if should_render_html(request):
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"request": request, "ip": ip, "version": version},
            headers=CACHE_HEADERS,
        )

    # Default to plain text with trailing newline for curl, scripts, etc.
    return PlainTextResponse(
        status_code=200,
        content=f"{ip}\n",
        headers=CACHE_HEADERS,
    )

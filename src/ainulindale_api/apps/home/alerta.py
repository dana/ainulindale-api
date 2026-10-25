from __future__ import annotations

import logging
import os
import re

import httpx
from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import auth, models

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/alerta", tags=["home-alerta"])

templates_dir = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=templates_dir)

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-length",
    "host",
}


def get_upstream_url() -> str:
    return os.getenv("HOME_ALERTA_UPSTREAM_URL", "http://192.168.1.247:8080").rstrip(
        "/"
    )


def get_request_timeout() -> float:
    try:
        return float(os.getenv("HOME_ALERTA_TIMEOUT", "10.0"))
    except ValueError:
        return 10.0


async def authenticate_request(
    request: Request,
) -> tuple[models.HomeSession | None, Response | None]:
    """Verify session authentication and allowlist.

    Returns (session, None) if authorized, or (None, Response) if rejected.
    """
    session_id = auth.get_session_cookie(request)
    session = None
    if session_id:
        try:
            session = await models.get_session(session_id)
        except Exception:
            session = None

    if not session or not session.is_authenticated:
        accept = request.headers.get("accept", "")
        if "application/json" in accept or request.url.path.startswith(
            "/home/alerta/api"
        ):
            return None, JSONResponse(
                status_code=401,
                content={"detail": "Authentication required"},
            )
        return None, RedirectResponse(url="/home/auth/google/login", status_code=303)

    if not auth.is_email_allowed(session.email):
        return None, templates.TemplateResponse(
            request=request,
            name="unauthorized.html",
            context={
                "email": session.email,
                "name": session.name,
                "allowlist": sorted(list(auth.get_allowlist())),
            },
            status_code=403,
        )

    return session, None


@router.get("", include_in_schema=False)
async def alerta_root_redirect():
    """Ensure trailing slash for correct relative asset resolution."""
    return RedirectResponse(url="/home/alerta/", status_code=303)


@router.get("/login", include_in_schema=False)
async def alerta_login_redirect():
    """Redirect Alerta login back to main console since auth is handled upstream."""
    return RedirectResponse(url="/home/alerta/", status_code=303)


@router.get("/config.json", include_in_schema=False)
async def alerta_config(request: Request):
    """Serve Alerta Web UI config customized for the /home/alerta mount path."""
    _, error_response = await authenticate_request(request)
    if error_response:
        return error_response

    config = {
        "endpoint": "/home/alerta/api",
        "base_path": "/home/alerta",
        "auth_required": False,
        "allow_readonly": True,
        "refresh_interval": 30000,
        "columns": [
            "severity",
            "status",
            "lastReceiveTime",
            "resource",
            "event",
            "value",
            "text",
            "grafana",
        ],
    }
    return JSONResponse(content=config)


@router.api_route(
    "/{subpath:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
    include_in_schema=False,
)
async def alerta_proxy(request: Request, subpath: str = ""):
    """Reverse proxy authenticated requests to upstream Alerta console and API."""
    _, error_response = await authenticate_request(request)
    if error_response:
        return error_response

    upstream_base = get_upstream_url()
    target_url = f"{upstream_base}/{subpath}" if subpath else f"{upstream_base}/"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    # Prepare forwarded headers
    forward_headers = {}
    for key, value in request.headers.items():
        if key.lower() not in HOP_BY_HOP_HEADERS:
            forward_headers[key] = value

    forward_headers["X-Forwarded-Proto"] = "https"
    forward_headers["X-Forwarded-Host"] = request.headers.get("host", "diederich.ai")
    forward_headers["X-Forwarded-Prefix"] = "/home/alerta"

    # Forward client IP
    client_ip = request.client.host if request.client else "127.0.0.1"
    existing_forwarded = request.headers.get("x-forwarded-for")
    forward_headers["X-Forwarded-For"] = (
        f"{existing_forwarded}, {client_ip}" if existing_forwarded else client_ip
    )

    body = await request.body()
    timeout = get_request_timeout()

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            upstream_res = await client.request(
                method=request.method,
                url=target_url,
                headers=forward_headers,
                content=body if body else None,
                follow_redirects=False,
            )
    except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as e:
        logger.error(f"Alerta upstream connection failed ({target_url}): {e}")
        accept = request.headers.get("accept", "")
        if "application/json" in accept or subpath.startswith("api"):
            return JSONResponse(
                status_code=502,
                content={
                    "detail": (
                        "Alerta upstream service unavailable. "
                        "Please check that monitoring-alerta daemon is running."
                    ),
                    "upstream": upstream_base,
                },
            )
        error_html = (
            "<!DOCTYPE html><html><head><title>Alerta Unavailable</title>"
            "<style>"
            "body{background:#0f172a;color:#f8fafc;font-family:sans-serif;"
            "padding:3rem;text-align:center;}"
            ".card{max-width:550px;margin:0 auto;background:#1e293b;"
            "border:1px solid #334155;border-radius:12px;padding:2rem;}"
            "h2{color:#f87171;}p{color:#94a3b8;line-height:1.6;}"
            "a{color:#38bdf8;text-decoration:none;}"
            "</style></head><body>"
            "<div class='card'><h2>🚨 Alerta Service Unavailable</h2>"
            "<p>Unable to connect to the upstream Alerta monitoring service at <code>"
            f"{upstream_base}"
            "</code>. Verify that the Docker container on Thalos is running.</p>"
            "<p><a href='/home/'>&larr; Return to Home Gateway</a></p>"
            "</div></body></html>"
        )
        return HTMLResponse(status_code=502, content=error_html)

    # Filter response headers
    response_headers = {}
    for key, val in upstream_res.headers.items():
        if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() != "content-encoding":
            response_headers[key] = val

    content_type = upstream_res.headers.get("content-type", "")

    # 1. HTML Rewriting for subpath-mounted SPA
    if "text/html" in content_type:
        text = upstream_res.text
        # Rewrite root-relative links (href, src, content) to point under /home/alerta/
        rewritten = re.sub(
            r"""(href|src|content)=["']/(?!home/)""",
            r'\1="/home/alerta/',
            text,
        )
        return HTMLResponse(
            content=rewritten,
            status_code=upstream_res.status_code,
            headers=response_headers,
        )

    # 2. JavaScript Rewriting for Webpack public path, loader, and initial auth
    if "javascript" in content_type:
        text = upstream_res.text
        # Rewrite webpack public path from "/" to "/home/alerta/"
        if 'c.p="/"' in text:
            text = text.replace('c.p="/"', 'c.p="/home/alerta/"')
        # Rewrite getLocalConfig to fetch /home/alerta/config.json
        old_config_call = 'var e="/";return this.$http.get("".concat(e,"config.json"))'
        new_config_call = (
            'var e="/home/alerta/";return this.$http.get("".concat(e,"config.json"))'
        )
        if old_config_call in text:
            text = text.replace(old_config_call, new_config_call)
        # Ensure default Vuex state has auth_required: false (prevents /login redirect)
        if "auth_required:!0" in text:
            text = text.replace("auth_required:!0", "auth_required:!1")
        return Response(
            content=text,
            media_type="application/javascript",
            status_code=upstream_res.status_code,
            headers=response_headers,
        )

    # 3. JSON Rewriting for API responses to clean upstream addresses
    if "application/json" in content_type:
        text = upstream_res.text
        if upstream_base in text:
            text = text.replace(f"{upstream_base}/api", "/home/alerta/api")
            text = text.replace(upstream_base, "/home/alerta")
        return Response(
            content=text,
            media_type="application/json",
            status_code=upstream_res.status_code,
            headers=response_headers,
        )

    # 4. Binary/Assets passthrough (CSS, images, fonts, audio)
    return Response(
        content=upstream_res.content,
        media_type=content_type,
        status_code=upstream_res.status_code,
        headers=response_headers,
    )

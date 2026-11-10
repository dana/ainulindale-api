from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re

import httpx
import websockets
from fastapi import (
    APIRouter,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import auth, models

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/grafana", tags=["home-grafana"])

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
    "accept-encoding",
}


def get_upstream_http_url() -> str:
    return os.getenv("HOME_GRAFANA_UPSTREAM_URL", "http://192.168.1.247:3000").rstrip(
        "/"
    )


def get_upstream_ws_url() -> str:
    http_url = get_upstream_http_url()
    if http_url.startswith("https://"):
        return "wss://" + http_url[8:]
    if http_url.startswith("http://"):
        return "ws://" + http_url[7:]
    return "ws://192.168.1.247:3000"


def get_request_timeout() -> float:
    try:
        return float(os.getenv("HOME_GRAFANA_TIMEOUT", "15.0"))
    except ValueError:
        return 15.0


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
            "/home/grafana/api"
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
                "allowlist": sorted(auth.get_allowlist()),
            },
            status_code=403,
        )

    return session, None


async def authenticate_ws(websocket: WebSocket) -> models.HomeSession | None:
    """Authenticate incoming WebSocket request using session cookie."""
    cookies = websocket.cookies
    session_id = cookies.get(auth.COOKIE_NAME)
    if not session_id:
        return None

    try:
        session = await models.get_session(session_id)
        if (
            session
            and session.is_authenticated
            and auth.is_email_allowed(session.email)
        ):
            return session
    except Exception as e:
        logger.warning(f"Error authenticating Grafana WebSocket session: {e}")
    return None


@router.get("", include_in_schema=False)
async def grafana_root_redirect():
    """Ensure trailing slash for correct relative asset resolution."""
    return RedirectResponse(url="/home/grafana/", status_code=303)


@router.websocket("/api/live/ws")
@router.websocket("/{ws_subpath:path}")
async def grafana_ws_proxy(websocket: WebSocket, ws_subpath: str = ""):
    """Reverse proxy authenticated WebSocket traffic to upstream Grafana Live."""
    session = await authenticate_ws(websocket)
    if not session:
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION, reason="Unauthorized"
        )
        return

    await websocket.accept()

    upstream_ws_base = get_upstream_ws_url()
    # Normalize subpath
    path = ws_subpath.lstrip("/")
    if websocket.url.path.endswith("/api/live/ws") and not path:
        path = "api/live/ws"
    target_ws_url = f"{upstream_ws_base}/{path}" if path else f"{upstream_ws_base}/"
    if websocket.url.query:
        target_ws_url = f"{target_ws_url}?{websocket.url.query}"

    upstream_headers = {
        "X-Webauth-User": session.email,
        "X-Webauth-Name": session.name or session.email,
        "X-Forwarded-Proto": "https",
        "X-Forwarded-Host": websocket.headers.get("host", "diederich.ai"),
        "X-Forwarded-Prefix": "/home/grafana",
    }
    client_ip = websocket.client.host if websocket.client else "127.0.0.1"
    upstream_headers["X-Forwarded-For"] = client_ip

    try:
        async with websockets.connect(
            target_ws_url,
            extra_headers=upstream_headers,
            ping_interval=20,
            ping_timeout=20,
        ) as upstream_ws:

            async def client_to_upstream():
                try:
                    while True:
                        msg = await websocket.receive()
                        if "text" in msg and msg["text"] is not None:
                            await upstream_ws.send(msg["text"])
                        elif "bytes" in msg and msg["bytes"] is not None:
                            await upstream_ws.send(msg["bytes"])
                except WebSocketDisconnect:
                    pass
                except Exception as ex:
                    logger.debug(f"Grafana client-to-upstream disconnect: {ex}")

            async def upstream_to_client():
                try:
                    async for msg in upstream_ws:
                        if isinstance(msg, str):
                            await websocket.send_text(msg)
                        else:
                            await websocket.send_bytes(msg)
                except Exception as ex:
                    logger.debug(f"Grafana upstream-to-client disconnect: {ex}")

            done, pending = await asyncio.wait(
                [
                    asyncio.create_task(client_to_upstream()),
                    asyncio.create_task(upstream_to_client()),
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    except Exception as e:
        logger.error(f"Grafana upstream WebSocket failed ({target_ws_url}): {e}")
        with contextlib.suppress(Exception):
            await websocket.close(
                code=status.WS_1011_INTERNAL_ERROR, reason="Upstream unavailable"
            )


@router.api_route(
    "/{subpath:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
    include_in_schema=False,
)
async def grafana_http_proxy(request: Request, subpath: str = ""):
    """Reverse proxy authenticated HTTP traffic to upstream Grafana."""
    session, error_resp = await authenticate_request(request)
    if error_resp:
        return error_resp

    upstream_base = get_upstream_http_url()
    target_url = f"{upstream_base}/{subpath}" if subpath else f"{upstream_base}/"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    forward_headers = {}
    for k, v in request.headers.items():
        k_lower = k.lower()
        if k_lower not in HOP_BY_HOP_HEADERS and k_lower != "x-forwarded-proto":
            forward_headers[k_lower] = v

    forward_headers["x-forwarded-proto"] = "https"
    forward_headers["x-forwarded-host"] = request.headers.get("host", "diederich.ai")
    forward_headers["x-forwarded-prefix"] = "/home/grafana"
    forward_headers["x-webauth-user"] = session.email
    forward_headers["x-webauth-name"] = session.name or session.email

    client_ip = request.client.host if request.client else "127.0.0.1"
    existing_fwd = request.headers.get("x-forwarded-for")
    forward_headers["x-forwarded-for"] = (
        f"{existing_fwd}, {client_ip}" if existing_fwd else client_ip
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
    except (
        httpx.ConnectError,
        httpx.TimeoutException,
        httpx.NetworkError,
    ) as e:
        logger.error(f"Grafana upstream connection failed ({target_url}): {e}")
        accept = request.headers.get("accept", "")
        if "application/json" in accept or subpath.startswith("api"):
            return JSONResponse(
                status_code=502,
                content={
                    "detail": "Grafana upstream service unavailable.",
                    "upstream": upstream_base,
                },
            )
        error_html = (
            "<!DOCTYPE html><html><head><title>Grafana Unavailable</title>"
            "<style>body{background:#0f172a;color:#f8fafc;font-family:sans-serif;"
            "padding:3rem;text-align:center;}"
            ".card{max-width:550px;margin:0 auto;background:#1e293b;"
            "border:1px solid #334155;border-radius:12px;padding:2rem;}"
            "h2{color:#f87171;}p{color:#94a3b8;line-height:1.6;}"
            "a{color:#38bdf8;text-decoration:none;}</style></head><body>"
            "<div class='card'><h2>🚨 Grafana Unavailable</h2>"
            "<p>Unable to connect to upstream monitoring service at "
            f"<code>{upstream_base}</code>.</p>"
            "<p><a href='/home/'>&larr; Return to Home Gateway</a></p>"
            "</div></body></html>"
        )
        return HTMLResponse(status_code=502, content=error_html)

    response_headers = {}
    for key, val in upstream_res.headers.items():
        k_lower = key.lower()
        if k_lower not in HOP_BY_HOP_HEADERS and k_lower != "content-encoding":
            if k_lower == "location":
                # Rewrite direct upstream IP/host redirect location to /home/grafana/
                loc = val
                if upstream_base in loc:
                    loc = loc.replace(upstream_base, "/home/grafana")
                elif loc.startswith("http://") or loc.startswith("https://"):
                    loc = re.sub(r"^https?://[^/]+", "/home/grafana", loc)
                response_headers[key] = loc
            else:
                response_headers[key] = val

    content_type = upstream_res.headers.get("content-type", "")

    return Response(
        content=upstream_res.content,
        media_type=content_type,
        status_code=upstream_res.status_code,
        headers=response_headers,
    )

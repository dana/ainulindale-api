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
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.templating import Jinja2Templates

from . import auth, models

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ha", tags=["home-ha"])
camera_router = APIRouter(tags=["home-ha-camera"])

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
    return os.getenv("HOME_ASSISTANT_UPSTREAM_URL", "http://192.168.1.247:8123").rstrip(
        "/"
    )


def get_upstream_ws_url() -> str:
    http_url = get_upstream_http_url()
    if http_url.startswith("https://"):
        return "wss://" + http_url[8:]
    if http_url.startswith("http://"):
        return "ws://" + http_url[7:]
    return "ws://192.168.1.247:8123"


def get_request_timeout() -> float:
    try:
        return float(os.getenv("HOME_ASSISTANT_TIMEOUT", "30.0"))
    except ValueError:
        return 30.0


async def authenticate_request(
    request: Request,
) -> tuple[models.HomeSession | None, Response | None]:
    """Verify session authentication and allowlist for Home Assistant access."""
    session_id = auth.get_session_cookie(request)
    session = None
    if session_id:
        try:
            session = await models.get_session(session_id)
        except Exception:
            session = None

    if not session or not session.is_authenticated:
        accept = request.headers.get("accept", "")
        if "application/json" in accept or request.url.path.startswith("/home/ha/api"):
            return None, JSONResponse(
                status_code=401,
                content={"detail": "Authentication required"},
            )
        return None, RedirectResponse(
            url="/home/auth/google/login?redirect=/home/ha/", status_code=303
        )

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


@router.websocket("/api/websocket")
async def ha_websocket_proxy(websocket: WebSocket):
    """Bidirectional WebSocket proxy tunnel to Home Assistant /api/websocket."""
    cookie_val = websocket.cookies.get(auth.COOKIE_NAME)
    session = None
    if cookie_val:
        try:
            session = await models.get_session(cookie_val)
        except Exception:
            session = None

    if (
        not session
        or not session.is_authenticated
        or not auth.is_email_allowed(session.email)
    ):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()

    upstream_ws_url = f"{get_upstream_ws_url()}/api/websocket"
    upstream_headers = {
        "X-Forwarded-User": session.email,
        "X-Forwarded-Email": session.email,
        "X-Forwarded-Name": session.name or "",
        "X-Forwarded-Proto": "https",
        "X-Forwarded-Host": "diederich.ai",
        "X-Forwarded-Prefix": "/home/ha",
    }

    try:
        async with websockets.connect(
            upstream_ws_url, additional_headers=upstream_headers
        ) as upstream_ws:

            async def client_to_upstream():
                try:
                    while True:
                        data = await websocket.receive()
                        if "text" in data and data["text"]:
                            await upstream_ws.send(data["text"])
                        elif "bytes" in data and data["bytes"]:
                            await upstream_ws.send(data["bytes"])
                except (WebSocketDisconnect, asyncio.CancelledError):
                    pass

            async def upstream_to_client():
                try:
                    async for message in upstream_ws:
                        if isinstance(message, str):
                            await websocket.send_text(message)
                        else:
                            await websocket.send_bytes(message)
                except (WebSocketDisconnect, asyncio.CancelledError):
                    pass

            done, pending = await asyncio.wait(
                [
                    asyncio.create_task(client_to_upstream()),
                    asyncio.create_task(upstream_to_client()),
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
    except Exception as e:
        logger.warning("HA WebSocket upstream tunnel exception: %s", e)
    finally:
        with contextlib.suppress(Exception):
            await websocket.close()


@router.get("", include_in_schema=False)
async def ha_root_redirect():
    """Ensure trailing slash for correct relative asset resolution."""
    return RedirectResponse(url="/home/ha/", status_code=303)


@router.api_route(
    "/{subpath:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
    include_in_schema=False,
)
async def ha_http_proxy(request: Request, subpath: str = ""):
    """Reverse proxy authenticated HTTP traffic to upstream Home Assistant."""
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
    forward_headers["x-forwarded-prefix"] = "/home/ha"
    forward_headers["x-forwarded-user"] = session.email
    forward_headers["x-forwarded-email"] = session.email
    forward_headers["x-forwarded-name"] = session.name or ""

    client_ip = request.client.host if request.client else "127.0.0.1"
    existing_fwd = request.headers.get("x-forwarded-for")
    forward_headers["x-forwarded-for"] = (
        f"{existing_fwd}, {client_ip}" if existing_fwd else client_ip
    )

    body = await request.body()
    timeout = get_request_timeout()

    is_stream = "camera_proxy_stream" in subpath or "camera_proxy_stream" in request.url.path
    if is_stream:
        try:
            client = httpx.AsyncClient(timeout=None)
            req = client.build_request(
                method=request.method,
                url=target_url,
                headers=forward_headers,
                content=body if body else None,
            )
            upstream_res = await client.send(req, stream=True)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as e:
            logger.error(f"Home Assistant upstream stream failed ({target_url}): {e}")
            return JSONResponse(
                status_code=502,
                content={"detail": "Home Assistant upstream camera stream unavailable."},
            )

        async def stream_generator():
            try:
                async for chunk in upstream_res.aiter_raw():
                    yield chunk
            finally:
                await upstream_res.aclose()
                await client.aclose()

        response_headers = {}
        for key, val in upstream_res.headers.items():
            if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() != "content-encoding":
                response_headers[key] = val

        return StreamingResponse(
            stream_generator(),
            status_code=upstream_res.status_code,
            headers=response_headers,
            media_type=upstream_res.headers.get(
                "content-type", "multipart/x-mixed-replace; boundary=--frameboundary"
            ),
        )

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
        logger.error(f"Home Assistant upstream connection failed ({target_url}): {e}")
        accept = request.headers.get("accept", "")
        if "application/json" in accept or subpath.startswith("api"):
            return JSONResponse(
                status_code=502,
                content={
                    "detail": "Home Assistant upstream service unavailable.",
                    "upstream": upstream_base,
                },
            )
        error_html = (
            "<!DOCTYPE html><html><head><title>Home Assistant Unavailable</title>"
            "<style>body{background:#0f172a;color:#f8fafc;font-family:sans-serif;"
            "padding:3rem;text-align:center;}"
            ".card{max-width:550px;margin:0 auto;background:#1e293b;"
            "border:1px solid #334155;border-radius:12px;padding:2rem;}"
            "h2{color:#f87171;}p{color:#94a3b8;line-height:1.6;}"
            "a{color:#38bdf8;text-decoration:none;}</style></head><body>"
            "<div class='card'><h2>🚨 Home Assistant Unavailable</h2>"
            "<p>Unable to connect to upstream service at "
            f"<code>{upstream_base}</code>.</p>"
            "<p><a href='/home/'>&larr; Return to Home Gateway</a></p>"
            "</div></body></html>"
        )
        return HTMLResponse(status_code=502, content=error_html)

    response_headers = {}
    for key, val in upstream_res.headers.items():
        if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() != "content-encoding":
            response_headers[key] = val

    content_type = upstream_res.headers.get("content-type", "")

    # 1. HTML Rewriting for subpath-mounted Home Assistant
    if "text/html" in content_type:
        text = upstream_res.text
        rewritten = re.sub(
            r'([("\'=`])/(frontend_|static/|auth/|manifest\.json|service_worker\.js|auth_header/)',
            r"\1/home/ha/\2",
            text,
        )
        return HTMLResponse(
            content=rewritten,
            status_code=upstream_res.status_code,
            headers=response_headers,
        )

    # 2. JavaScript Rewriting for subpath origin, chunk loading, auth and assets
    if "javascript" in content_type:
        text = upstream_res.text
        target_r = "const R=`${location.protocol}//${location.host}`"
        subpath_r = "const R=`${location.protocol}//${location.host}/home/ha`"
        if target_r in text:
            text = text.replace(target_r, subpath_r)

        target_a = "const A=()=>location.pathname"
        subpath_a = 'const A=()=>location.pathname.replace(/^\\/home\\/ha/,"")||"/"'
        if target_a in text:
            text = text.replace(target_a, subpath_a)

        target_push = 'r.pushState(h(t?.data,n.G.location.pathname),"",e)'
        subpath_push = 'r.pushState(h(t?.data,n.G.location.pathname),"",(typeof e==="string"&&e.startsWith("/")&&!e.startsWith("/home/ha")?"/home/ha"+e:e))'
        if target_push in text:
            text = text.replace(target_push, subpath_push)

        target_replace = 'r.replaceState(h(n,o),"",e)'
        subpath_replace = 'r.replaceState(h(n,o),"",(typeof e==="string"&&e.startsWith("/")&&!e.startsWith("/home/ha")?"/home/ha"+e:e))'
        if target_replace in text:
            text = text.replace(target_replace, subpath_replace)

        text = re.sub(
            r'([\"\'\`])/(frontend_|static/|auth/|manifest\.json|service_worker\.js|auth_header/)',
            r"\1/home/ha/\2",
            text,
        )

        return Response(
            content=text,
            media_type="application/javascript",
            status_code=upstream_res.status_code,
            headers=response_headers,
        )

    # 3. CSS Rewriting for static font / image references
    if "css" in content_type:
        text = upstream_res.text
        text = re.sub(
            r'([("\'=`])/(frontend_|static/)',
            r"\1/home/ha/\2",
            text,
        )
        return Response(
            content=text,
            media_type="text/css",
            status_code=upstream_res.status_code,
            headers=response_headers,
        )

    # 4. JSON and binary assets passthrough
    return Response(
        content=upstream_res.content,
        media_type=content_type,
        status_code=upstream_res.status_code,
        headers=response_headers,
    )


@camera_router.api_route(
    "/api/camera_proxy/{subpath:path}",
    methods=["GET", "OPTIONS", "HEAD"],
    include_in_schema=False,
)
@camera_router.api_route(
    "/api/camera_proxy_stream/{subpath:path}",
    methods=["GET", "OPTIONS", "HEAD"],
    include_in_schema=False,
)
@camera_router.api_route(
    "/api/image_proxy/{subpath:path}",
    methods=["GET", "OPTIONS", "HEAD"],
    include_in_schema=False,
)
@camera_router.api_route(
    "/api/image_proxy_stream/{subpath:path}",
    methods=["GET", "OPTIONS", "HEAD"],
    include_in_schema=False,
)
async def ha_camera_root_proxy(request: Request, subpath: str = ""):
    """Reverse proxy root-level camera and media proxy requests directly to Home Assistant."""
    session_id = auth.get_session_cookie(request)
    session = None
    if session_id:
        with contextlib.suppress(Exception):
            session = await models.get_session(session_id)

    is_auth = (
        session is not None
        and session.is_authenticated
        and auth.is_email_allowed(session.email)
    )
    has_token = bool(
        request.query_params.get("token") or request.query_params.get("authSig")
    )

    if not is_auth and not has_token:
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required"},
        )

    upstream_base = get_upstream_http_url()
    target_url = f"{upstream_base}{request.url.path}"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    forward_headers = {}
    for k, v in request.headers.items():
        k_lower = k.lower()
        if k_lower not in HOP_BY_HOP_HEADERS and k_lower != "x-forwarded-proto":
            forward_headers[k_lower] = v

    forward_headers["x-forwarded-proto"] = "https"
    forward_headers["x-forwarded-host"] = request.headers.get("host", "diederich.ai")
    if is_auth and session:
        forward_headers["x-forwarded-user"] = session.email
        forward_headers["x-forwarded-email"] = session.email
        forward_headers["x-forwarded-name"] = session.name or ""

    is_stream = "stream" in request.url.path
    if is_stream:
        try:
            client = httpx.AsyncClient(timeout=None)
            req = client.build_request(
                method=request.method,
                url=target_url,
                headers=forward_headers,
            )
            upstream_res = await client.send(req, stream=True)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as e:
            logger.error(
                f"Home Assistant camera stream connection failed ({target_url}): {e}"
            )
            return JSONResponse(
                status_code=502,
                content={"detail": "Camera stream unavailable."},
            )

        async def stream_generator():
            try:
                async for chunk in upstream_res.aiter_raw():
                    yield chunk
            finally:
                await upstream_res.aclose()
                await client.aclose()

        response_headers = {}
        for key, val in upstream_res.headers.items():
            if (
                key.lower() not in HOP_BY_HOP_HEADERS
                and key.lower() != "content-encoding"
            ):
                response_headers[key] = val

        return StreamingResponse(
            stream_generator(),
            status_code=upstream_res.status_code,
            headers=response_headers,
            media_type=upstream_res.headers.get(
                "content-type", "multipart/x-mixed-replace; boundary=--frameboundary"
            ),
        )

    timeout = get_request_timeout()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            upstream_res = await client.request(
                method=request.method,
                url=target_url,
                headers=forward_headers,
                follow_redirects=False,
            )
    except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as e:
        logger.error(
            f"Home Assistant camera proxy connection failed ({target_url}): {e}"
        )
        return JSONResponse(
            status_code=502,
            content={"detail": "Camera snapshot unavailable."},
        )

    response_headers = {}
    for key, val in upstream_res.headers.items():
        if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() != "content-encoding":
            response_headers[key] = val

    return Response(
        content=upstream_res.content,
        media_type=upstream_res.headers.get("content-type", "image/jpeg"),
        status_code=upstream_res.status_code,
        headers=response_headers,
    )

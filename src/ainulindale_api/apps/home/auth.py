from __future__ import annotations

import contextlib
import datetime
import os
import secrets
import urllib.parse

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from . import models

router = APIRouter(prefix="/auth", tags=["home-auth"])

templates_dir = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=templates_dir)

COOKIE_NAME = "ainulindale_home_session"
DEFAULT_ALLOWLIST = {"diederich@gmail.com", "msdiederich@gmail.com"}


def get_allowlist() -> set[str]:
    raw = os.getenv("HOME_ALLOWLIST_EMAILS")
    if not raw:
        return DEFAULT_ALLOWLIST
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def is_email_allowed(email: str | None) -> bool:
    if not email:
        return False
    return email.strip().lower() in get_allowlist()


def get_oauth_client_id() -> str:
    return os.getenv("HOME_GOOGLE_OAUTH_CLIENT_ID") or os.getenv(
        "GOOGLE_OAUTH_CLIENT_ID", ""
    )


def get_oauth_client_secret() -> str:
    return os.getenv("HOME_GOOGLE_OAUTH_CLIENT_SECRET") or os.getenv(
        "GOOGLE_OAUTH_CLIENT_SECRET", ""
    )


def get_oauth_redirect_uri() -> str:
    return (
        os.getenv("HOME_GOOGLE_OAUTH_REDIRECT_URI")
        or "https://diederich.ai/home/auth/google/callback"
    )


def get_oauth_scopes() -> str:
    return os.getenv("HOME_GOOGLE_OAUTH_SCOPES", "openid email profile")


def get_session_cookie(request: Request) -> str | None:
    return request.cookies.get(COOKIE_NAME)


def set_session_cookie(response: Response, session: models.HomeSession):
    cookie_path = os.getenv("HOME_COOKIE_PATH", "/")
    max_age = 30 * 24 * 60 * 60  # 30 days
    expires = datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=max_age)
    response.set_cookie(
        key=COOKIE_NAME,
        value=session.id,
        max_age=max_age,
        expires=expires,
        httponly=True,
        samesite="lax",
        path=cookie_path,
        secure=True,
    )


def clear_session_cookie(response: Response):
    cookie_path = os.getenv("HOME_COOKIE_PATH", "/")
    response.delete_cookie(
        key=COOKIE_NAME,
        path=cookie_path,
        httponly=True,
        samesite="lax",
        secure=True,
    )


async def get_current_user_and_session(
    request: Request,
) -> tuple[models.HomeSession | None, models.HomeUser | None]:
    session_id = get_session_cookie(request)
    if not session_id:
        return None, None
    try:
        session = await models.get_session(session_id)
    except Exception:
        session = None
    if not session or not session.is_authenticated:
        return None, None
    if not is_email_allowed(session.email):
        return None, None
    user = None
    if session.user_id:
        try:
            user = await models.get_user(session.user_id)
        except Exception:
            user = None
    return session, user


@router.get("/google/login", include_in_schema=False)
async def google_login(request: Request):
    client_id = get_oauth_client_id()
    if not client_id:
        raise HTTPException(
            status_code=500,
            detail="Google OAuth Client ID is not configured.",
        )

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)

    # Store a pending session with state & nonce
    session = await models.create_session(state=state, nonce=nonce, duration_days=1)

    redirect_uri = get_oauth_redirect_uri()
    scopes = get_oauth_scopes()

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scopes,
        "state": state,
        "nonce": nonce,
        "prompt": "select_account",
    }
    auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"
    )

    response = RedirectResponse(url=auth_url, status_code=303)
    set_session_cookie(response, session)
    return response


@router.get("/google/callback", include_in_schema=False)
async def google_callback(
    request: Request,
    response: Response,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    if error:
        raise HTTPException(status_code=400, detail=f"Google OAuth error: {error}")

    if not code or not state:
        raise HTTPException(
            status_code=400, detail="Missing authorization code or state"
        )

    session_id = get_session_cookie(request)
    if not session_id:
        raise HTTPException(status_code=400, detail="No session cookie provided")

    session = await models.get_session(session_id)
    if not session or session.state != state:
        raise HTTPException(status_code=400, detail="Invalid state or session mismatch")

    nonce = session.nonce
    await models.update_session(session.id, state=None, nonce=None)

    client_id = get_oauth_client_id()
    client_secret = get_oauth_client_secret()
    redirect_uri = get_oauth_redirect_uri()

    if not client_id or not client_secret:
        raise HTTPException(
            status_code=500, detail="Google OAuth credentials not configured"
        )

    async with httpx.AsyncClient() as client:
        token_res = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if token_res.status_code != 200:
            raise HTTPException(
                status_code=400, detail="Failed to exchange authorization code"
            )

        token_data = token_res.json()
        id_token_jwt = token_data.get("id_token")

    if not id_token_jwt:
        raise HTTPException(status_code=400, detail="No id_token returned by Google")

    try:
        req = google_requests.Request()
        id_info = id_token.verify_oauth2_token(id_token_jwt, req, client_id)
        if nonce and id_info.get("nonce") != nonce:
            raise ValueError("Nonce mismatch")
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Token verification failed: {e}"
        ) from e

    google_sub = id_info.get("sub", "")
    email = id_info.get("email", "")
    name = id_info.get("name", "")

    # Check allowlist
    if not is_email_allowed(email):
        # Delete pending session and clear cookie
        await models.delete_session(session.id)
        resp = templates.TemplateResponse(
            request=request,
            name="unauthorized.html",
            context={
                "email": email,
                "name": name,
                "allowlist": sorted(list(get_allowlist())),
            },
            status_code=403,
        )
        clear_session_cookie(resp)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    # Email is allowlisted!
    # Get or create User
    user = await models.get_user_by_sub(google_sub)
    if not user:
        user = await models.create_user(google_sub=google_sub, email=email, name=name)
    else:
        await models.update_user_login(user.id)

    # Rotate session to a fresh authenticated session
    await models.delete_session(session.id)
    new_session = await models.create_session(
        user_id=user.id,
        email=email,
        name=name,
        is_authenticated=True,
        duration_days=30,
    )

    redirect_res = RedirectResponse(url="/home/", status_code=303)
    set_session_cookie(redirect_res, new_session)
    redirect_res.headers["Cache-Control"] = "no-store"
    redirect_res.headers["Referrer-Policy"] = "no-referrer"
    return redirect_res


@router.post("/signout", include_in_schema=False)
@router.get("/signout", include_in_schema=False)
async def signout(request: Request):
    session_id = get_session_cookie(request)
    if session_id:
        with contextlib.suppress(Exception):
            await models.delete_session(session_id)

    response = RedirectResponse(url="/home/", status_code=303)
    clear_session_cookie(response)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/verify", include_in_schema=False)
async def verify(request: Request):
    """ForwardAuth / Traefik verification endpoint for future consolidated apps."""
    session, user = await get_current_user_and_session(request)
    if not session or not session.is_authenticated or not session.email:
        return JSONResponse(
            status_code=401,
            content={"status": "unauthorized", "detail": "Authentication required"},
        )

    headers = {
        "X-Forwarded-User": session.email,
        "X-Forwarded-Name": session.name or "",
    }
    return JSONResponse(
        status_code=200,
        content={"status": "authorized", "user": session.email},
        headers=headers,
    )

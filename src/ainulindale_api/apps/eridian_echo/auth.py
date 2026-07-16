import datetime
import os
import secrets
import uuid

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from . import models

router = APIRouter(prefix="/auth", tags=["auth"])

def get_session_cookie(request: Request) -> str | None:
    return request.cookies.get("eridian_echo_session")

async def get_or_create_session(request: Request) -> tuple[models.Session, bool]:
    session_id = get_session_cookie(request)
    session = None
    if session_id:
        session = await models.get_session(session_id)
    
    is_new = False
    if not session:
        principal_id = str(uuid.uuid4())
        session = await models.create_session(principal_id)
        is_new = True
        
    return session, is_new

def set_session_cookie(response: Response, session: models.Session):
    max_age = 10 * 365 * 24 * 60 * 60  # 10 years
    response.set_cookie(
        key="eridian_echo_session",
        value=session.id,
        max_age=max_age,
        expires=datetime.datetime.now(datetime.UTC)
        + datetime.timedelta(seconds=max_age),
        httponly=True,
        samesite="lax",
        path="/api/v1/eridian-echo",
        secure=True
    )

@router.get("/google/login")
async def google_login(request: Request):
    session, is_new = await get_or_create_session(request)
    
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    
    await models.update_session(session.id, state=state, nonce=nonce)
    
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    redirect_uri = os.environ.get("GOOGLE_OAUTH_REDIRECT_URI")
    scopes = os.environ.get("GOOGLE_OAUTH_SCOPES", "openid email profile")
    
    auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={client_id}&"
        f"redirect_uri={redirect_uri}&"
        f"response_type=code&"
        f"scope={scopes}&"
        f"state={state}&"
        f"nonce={nonce}"
    )
    
    response = RedirectResponse(url=auth_url, status_code=303)
    if is_new:
        set_session_cookie(response, session)
    return response


@router.get("/google/callback")
async def google_callback(request: Request, response: Response, code: str, state: str):
    session_id = get_session_cookie(request)
    if not session_id:
        raise HTTPException(status_code=400, detail="No session cookie")
    
    session = await models.get_session(session_id)
    if not session or session.state != state:
        raise HTTPException(status_code=400, detail="Invalid state or session")
    
    # Clear state and nonce from DB
    nonce = session.nonce
    await models.update_session(session.id, state=None, nonce=None)
    
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
    redirect_uri = os.environ.get("GOOGLE_OAUTH_REDIRECT_URI")
    
    # Exchange code for token
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
            raise HTTPException(status_code=400, detail="Failed to exchange code")
        
        token_data = token_res.json()
        id_token_jwt = token_data.get("id_token")
    
    if not id_token_jwt:
        raise HTTPException(status_code=400, detail="No id_token returned")
    
    # Verify ID token
    try:
        req = google_requests.Request()
        id_info = id_token.verify_oauth2_token(id_token_jwt, req, client_id)
        if id_info["nonce"] != nonce:
            raise ValueError("Nonce mismatch")
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail=f"Token verification failed: {e}"
        ) from e
    
    google_sub = id_info.get("sub")
    email = id_info.get("email", "")
    name = id_info.get("name", "")
    
    # Get or create User
    user = await models.get_user_by_sub(google_sub)
    if not user:
        user = await models.create_user(google_sub=google_sub, email=email, name=name)
    
    # Link guest jobs to new user
    if not session.is_authenticated:
        await models.link_jobs_to_user(session.principal_id, user.id)
    
    # Rotate session
    await models.delete_session(session.id)
    new_session = await models.create_session(
        principal_id=user.id, is_authenticated=True
    )
    
    redirect_res = RedirectResponse(url="/api/v1/eridian-echo/", status_code=303)
    set_session_cookie(redirect_res, new_session)
    
    # Required by instructions for callback
    redirect_res.headers["Cache-Control"] = "no-store"
    redirect_res.headers["Referrer-Policy"] = "no-referrer"
    return redirect_res


@router.post("/signout")
async def signout(request: Request, response: Response):
    session_id = get_session_cookie(request)
    if session_id:
        await models.delete_session(session_id)
        
    # Clear cookie
    response.delete_cookie(
        key="eridian_echo_session",
        path="/api/v1/eridian-echo",
        httponly=True,
        samesite="lax",
        secure=True
    )
    
    return RedirectResponse(url="/api/v1/eridian-echo/", status_code=303)

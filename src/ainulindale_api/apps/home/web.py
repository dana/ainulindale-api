from __future__ import annotations

import os

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from . import alerta, auth, common, ha

router = APIRouter()

templates_dir = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=templates_dir)

# Mount the auth routes (/auth/google/login, /auth/google/callback, etc.)
router.include_router(auth.router)

# Mount home-common routes (/common, /common/{file_path:path})
router.include_router(common.router)

# Mount alerta console reverse-proxy routes (/alerta, /alerta/{subpath:path})
router.include_router(alerta.router)

# Mount Home Assistant reverse-proxy routes (/ha, /ha/{subpath:path})
router.include_router(ha.router)


@router.get("", include_in_schema=False)
@router.get("/", include_in_schema=False)
async def home_index(request: Request):
    session, user = await auth.get_current_user_and_session(request)
    if not session or not session.is_authenticated:
        # Require Google authentication
        return RedirectResponse(url="/home/auth/google/login", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="welcome.html",
        context={
            "request": request,
            "session": session,
            "user": user,
            "email": session.email,
            "name": session.name or session.email,
        },
    )

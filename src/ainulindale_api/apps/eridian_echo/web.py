import os

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from . import auth, models

router = APIRouter()

# Setup templates directory
templates_dir = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=templates_dir)

# Include the auth router
router.include_router(auth.router)

@router.get("/", include_in_schema=False)
async def get_eridian_echo(request: Request):
    session, is_new = await auth.get_or_create_session(request)
    
    user = None
    if session.is_authenticated:
        user = await models.get_user(session.principal_id)
        
    response = templates.TemplateResponse(
        request=request, 
        name="index.html", 
        context={
            "is_authenticated": session.is_authenticated,
            "user": user
        }
    )
    if is_new:
        auth.set_session_cookie(response, session)
    return response


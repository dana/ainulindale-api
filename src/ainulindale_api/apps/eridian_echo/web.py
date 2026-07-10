import uuid
import datetime
from fastapi import APIRouter, Request, Response
from fastapi.templating import Jinja2Templates
import os

router = APIRouter()

# Setup templates directory
templates_dir = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=templates_dir)

@router.get("/", include_in_schema=False)
async def get_eridian_echo(request: Request):
    # Returning the template response
    response = templates.TemplateResponse(request=request, name="index.html")
    
    # Check for anonymous owner cookie
    owner_id = request.cookies.get("eridian_echo_owner")
    if not owner_id:
        owner_id = str(uuid.uuid4())
        # The user requested a "forever cookie"
        max_age = 10 * 365 * 24 * 60 * 60 # 10 years
        # Set the cookie on the response
        response.set_cookie(
            key="eridian_echo_owner", 
            value=owner_id, 
            max_age=max_age,
            expires=datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=max_age),
            httponly=True, 
            samesite='lax'
        )
    return response

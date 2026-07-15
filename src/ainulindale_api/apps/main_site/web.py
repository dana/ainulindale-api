import os

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


@router.get("/privacy.html", response_class=FileResponse, include_in_schema=False)
async def privacy():
    return os.path.join(BASE_DIR, "static", "privacy.html")


@router.get("/terms.html", response_class=FileResponse, include_in_schema=False)
async def terms():
    return os.path.join(BASE_DIR, "static", "terms.html")

from __future__ import annotations

import datetime
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import auth, models

router = APIRouter(prefix="/common", tags=["home-common"])

templates_dir = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=templates_dir)


def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


def get_home_common_dir() -> Path:
    env_dir = os.getenv("HOME_COMMON_DIR")
    if env_dir:
        return Path(env_dir).resolve()
    # Check production container mount
    container_mount = Path("/data/home-common")
    if container_mount.exists():
        return container_mount.resolve()
    # Fallback to local host directory
    local_path = Path(os.path.expanduser("~/home-common"))
    return local_path.resolve()


@router.get("", include_in_schema=False)
@router.get("/", include_in_schema=False)
@router.get("/{file_path:path}", include_in_schema=False)
async def serve_home_common(request: Request, file_path: str = ""):
    session_id = auth.get_session_cookie(request)
    session = None
    if session_id:
        try:
            session = await models.get_session(session_id)
        except Exception:
            session = None

    if not session or not session.is_authenticated:
        accept = request.headers.get("accept", "")
        if "application/json" in accept:
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required"},
            )
        return RedirectResponse(url="/home/auth/google/login", status_code=303)

    if not auth.is_email_allowed(session.email):
        return templates.TemplateResponse(
            request=request,
            name="unauthorized.html",
            context={
                "email": session.email,
                "name": session.name,
                "allowlist": sorted(list(auth.get_allowlist())),
            },
            status_code=403,
        )

    base_dir = get_home_common_dir()
    if not base_dir.exists():
        raise HTTPException(status_code=404, detail="home-common storage not found")

    # Secure path resolution against traversal attacks
    target = (base_dir / file_path).resolve()
    if target != base_dir and base_dir not in target.parents:
        raise HTTPException(status_code=404, detail="File not found")

    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")

    if target.is_file():
        return FileResponse(path=str(target), filename=target.name)

    # Directory listing
    items = []
    try:
        entries = sorted(
            target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Cannot read directory: {e}"
        ) from e

    # Build relative URL prefix
    rel_path = target.relative_to(base_dir)
    rel_str = str(rel_path) if str(rel_path) != "." else ""

    for entry in entries:
        # Hide internal anchor or dotfiles
        if entry.name.startswith("."):
            continue
        try:
            stat = entry.stat()
            mtime = datetime.datetime.fromtimestamp(stat.st_mtime, tz=datetime.UTC)
            mtime_str = mtime.strftime("%Y-%m-%d %H:%M")
            size_str = "-" if entry.is_dir() else format_size(stat.st_size)
        except Exception:
            mtime_str = "-"
            size_str = "-"

        item_subpath = f"{rel_str}/{entry.name}".strip("/")
        items.append(
            {
                "name": entry.name,
                "is_dir": entry.is_dir(),
                "size_str": size_str,
                "mtime_str": mtime_str,
                "url": f"/home/common/{item_subpath}",
            }
        )

    # Build breadcrumbs
    breadcrumbs = []
    if rel_str:
        accum = ""
        for part in rel_str.split("/"):
            accum = f"{accum}/{part}".strip("/")
            breadcrumbs.append({"name": part, "url": f"/home/common/{accum}"})

    parent_url = None
    if rel_str:
        parent_parts = rel_str.split("/")[:-1]
        if parent_parts:
            parent_url = f"/home/common/{'/'.join(parent_parts)}"
        else:
            parent_url = "/home/common"

    return templates.TemplateResponse(
        request=request,
        name="common_list.html",
        context={
            "request": request,
            "email": session.email,
            "items": items,
            "breadcrumbs": breadcrumbs,
            "parent_url": parent_url,
        },
    )

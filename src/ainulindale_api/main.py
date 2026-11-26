import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from motor.motor_asyncio import AsyncIOMotorClient

from ainulindale_api.api.v1.health import root_router as health_root_router
from ainulindale_api.api.v1.router import create_api_v1_router
from ainulindale_api.apps.eridian_echo.web import router as eridian_echo_router
from ainulindale_api.apps.home.ha import camera_router as ha_camera_router
from ainulindale_api.apps.home.ha import media_router as ha_media_router
from ainulindale_api.apps.home.web import router as home_router
from ainulindale_api.apps.ip.router import router as ip_router
from ainulindale_api.apps.main_site.web import router as main_site_router
from ainulindale_api.apps.ops_console.web import router as ops_console_router
from ainulindale_api.apps.share.web import router as share_router
from ainulindale_api.core import db
from ainulindale_api.core.routing import enforce_public_json_request_contract
from ainulindale_api.core.static_assets import mount_static_assets


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    db.client = AsyncIOMotorClient(db.MONGO_URI, serverSelectionTimeoutMS=2000)
    db.db = db.client[db.DATABASE_NAME]
    yield
    # Shutdown
    if db.client:
        db.client.close()


def create_app(enable_eridian_echo: bool | None = None) -> FastAPI:
    if enable_eridian_echo is None:
        enable_eridian_echo = os.getenv("ENABLE_ERIDIAN_ECHO", "false").lower() in (
            "true",
            "1",
            "yes",
        )

    app = FastAPI(
        lifespan=lifespan,
        title="Ainulindale API",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
    )

    app.middleware("http")(enforce_public_json_request_contract)

    # Health and ready endpoints at the root
    app.include_router(health_root_router)

    # API v1
    app.include_router(create_api_v1_router(enable_eridian_echo=enable_eridian_echo))

    # HTML Apps
    app.include_router(main_site_router, prefix="")
    app.include_router(home_router, prefix="/home")
    if enable_eridian_echo:
        app.include_router(eridian_echo_router, prefix="/api/v1/eridian-echo")
    app.include_router(ops_console_router, prefix="/ops")
    app.include_router(share_router, prefix="/s")
    app.include_router(ip_router)

    # Camera and stream proxy endpoints directly forwarded to Home Assistant
    app.include_router(ha_camera_router)
    app.include_router(ha_media_router)

    # Redirect root-level Home Assistant panel requests to authenticated subpath
    @app.get("/live-cameras", include_in_schema=False)
    @app.get("/live-cameras/{subpath:path}", include_in_schema=False)
    async def redirect_live_cameras(subpath: str = ""):
        target = (
            f"/home/ha/live-cameras/{subpath}" if subpath else "/home/ha/live-cameras"
        )
        return RedirectResponse(url=target, status_code=307)

    @app.get("/lovelace", include_in_schema=False)
    @app.get("/lovelace/{subpath:path}", include_in_schema=False)
    async def redirect_lovelace(subpath: str = ""):
        target = f"/home/ha/lovelace/{subpath}" if subpath else "/home/ha/lovelace"
        return RedirectResponse(url=target, status_code=307)

    # Static assets
    mount_static_assets(app, enable_eridian_echo=enable_eridian_echo)

    return app


app = create_app()

from contextlib import asynccontextmanager
from fastapi import FastAPI

from ainulindale_api.api.v1.health import root_router as health_root_router
from ainulindale_api.api.v1.router import api_v1_router
from ainulindale_api.apps.eridian_echo.web import router as eridian_echo_router
from ainulindale_api.apps.main_site.web import router as main_site_router
from ainulindale_api.apps.ops_console.web import router as ops_console_router
from ainulindale_api.apps.share.web import router as share_router
from ainulindale_api.core.routing import enforce_public_json_request_contract
from ainulindale_api.core.static_assets import mount_static_assets
from ainulindale_api.core import db
from motor.motor_asyncio import AsyncIOMotorClient

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    db.client = AsyncIOMotorClient(db.MONGO_URI)
    db.db = db.client[db.DATABASE_NAME]
    yield
    # Shutdown
    if db.client:
        db.client.close()

def create_app() -> FastAPI:
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
    app.include_router(api_v1_router)

    # HTML Apps
    app.include_router(main_site_router, prefix="")
    app.include_router(eridian_echo_router, prefix="/eridian-echo")
    app.include_router(ops_console_router, prefix="/ops")
    app.include_router(share_router, prefix="/s")

    # Static assets
    mount_static_assets(app)

    return app

app = create_app()

import os

from fastapi import APIRouter

from ainulindale_api.api.v1.echo import router as echo_router
from ainulindale_api.api.v1.health import v1_health_router
from ainulindale_api.apps.eridian_echo.api import router as eridian_echo_api_router
from ainulindale_api.apps.health_connect.router import router as health_connect_router
from ainulindale_api.core.routing import API_V1_PREFIX


def create_api_v1_router(enable_eridian_echo: bool = False) -> APIRouter:
    router = APIRouter(prefix=API_V1_PREFIX, tags=["api-v1"])
    router.include_router(echo_router)
    router.include_router(v1_health_router)
    if enable_eridian_echo:
        router.include_router(eridian_echo_api_router, prefix="/eridian-echo")
    router.include_router(health_connect_router, prefix="/health-connect")
    return router


api_v1_router = create_api_v1_router(
    enable_eridian_echo=os.getenv("ENABLE_ERIDIAN_ECHO", "false").lower()
    in ("true", "1", "yes")
)

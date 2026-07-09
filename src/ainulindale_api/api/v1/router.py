from fastapi import APIRouter

from ainulindale_api.api.v1.echo import router as echo_router
from ainulindale_api.api.v1.health import v1_health_router
from ainulindale_api.core.routing import API_V1_PREFIX

api_v1_router = APIRouter(prefix=API_V1_PREFIX, tags=["api-v1"])
api_v1_router.include_router(echo_router)
api_v1_router.include_router(v1_health_router)

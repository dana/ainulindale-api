import os
from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str

class ReadyResponse(BaseModel):
    status: str

class LoadAverage(BaseModel):
    one_minute: float
    five_minutes: float
    fifteen_minutes: float

class HappyResponse(BaseModel):
    system_time_utc: str
    load_average: LoadAverage

root_router = APIRouter(tags=["operational"])
v1_health_router = APIRouter()

@root_router.get("/healthz", response_model=HealthResponse)
def healthz() -> HealthResponse:
    return HealthResponse(status="ok")

@root_router.get("/readyz", response_model=ReadyResponse)
def readyz() -> ReadyResponse:
    return ReadyResponse(status="ready")

@v1_health_router.get("/happy", response_model=HappyResponse)
def happy() -> HappyResponse:
    load1, load5, load15 = os.getloadavg()
    return HappyResponse(
        system_time_utc=datetime.now(UTC).isoformat(),
        load_average=LoadAverage(
            one_minute=load1,
            five_minutes=load5,
            fifteen_minutes=load15,
        ),
    )

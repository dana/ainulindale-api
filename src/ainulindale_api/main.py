from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from fastapi import APIRouter, FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

API_V1_PREFIX = "/api/v1"
JSON_BODY_METHODS = {"POST", "PUT", "PATCH"}


class HealthResponse(BaseModel):
    status: str


class ReadyResponse(BaseModel):
    status: str


class EchoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(..., min_length=1, max_length=200)


class EchoResponse(BaseModel):
    message: str
    length: int


class HappyPathRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(..., min_length=1, max_length=200)


class HappyPathResponse(BaseModel):
    message: str
    proof: str
    length: int


class LoadAverage(BaseModel):
    one_minute: float
    five_minutes: float
    fifteen_minutes: float


class HappyResponse(BaseModel):
    system_time_utc: str
    load_average: LoadAverage


class ContractErrorResponse(BaseModel):
    detail: str


def _media_type(content_type: str | None) -> str | None:
    if content_type is None:
        return None

    return content_type.split(";", 1)[0].strip().lower()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Ainulindale API",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
    )

    @app.middleware("http")
    async def enforce_public_json_request_contract(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        is_public_application_path = request.url.path.startswith(f"{API_V1_PREFIX}/")
        method_can_have_json_body = request.method in JSON_BODY_METHODS

        if (
            is_public_application_path
            and method_can_have_json_body
            and _media_type(request.headers.get("content-type")) != "application/json"
        ):
            return JSONResponse(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                content={
                    "detail": (
                        "Public application endpoints with request bodies require "
                        "Content-Type: application/json"
                    )
                },
            )

        return await call_next(request)

    @app.get("/healthz", response_model=HealthResponse, tags=["operational"])
    def healthz() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/readyz", response_model=ReadyResponse, tags=["operational"])
    def readyz() -> ReadyResponse:
        return ReadyResponse(status="ready")

    api_v1 = APIRouter(prefix=API_V1_PREFIX, tags=["api-v1"])

    @api_v1.post(
        "/echo",
        response_model=EchoResponse,
        responses={
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {
                "model": ContractErrorResponse,
                "description": "Request body Content-Type is not application/json",
            }
        },
    )
    def echo(payload: EchoRequest) -> EchoResponse:
        return EchoResponse(message=payload.message, length=len(payload.message))

    @api_v1.post(
        "/happy-path",
        response_model=HappyPathResponse,
        responses={
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {
                "model": ContractErrorResponse,
                "description": "Request body Content-Type is not application/json",
            }
        },
    )
    def happy_path(payload: HappyPathRequest) -> HappyPathResponse:
        return HappyPathResponse(
            message=payload.message,
            proof="chunk-11-happy-path",
            length=len(payload.message),
        )

    @api_v1.get("/happy", response_model=HappyResponse)
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

    app.include_router(api_v1)

    return app


app = create_app()

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, Field


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

class ContractErrorResponse(BaseModel):
    detail: str

router = APIRouter()

@router.post(
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

@router.post(
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

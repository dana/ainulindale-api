from collections.abc import Awaitable, Callable

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse

API_V1_PREFIX = "/api/v1"
JSON_BODY_METHODS = {"POST", "PUT", "PATCH"}

def _media_type(content_type: str | None) -> str | None:
    if content_type is None:
        return None
    return content_type.split(";", 1)[0].strip().lower()

async def enforce_public_json_request_contract(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    is_public_application_path = request.url.path.startswith(f"{API_V1_PREFIX}/")
    is_upload_path = request.url.path.endswith("/upload")
    method_can_have_json_body = request.method in JSON_BODY_METHODS

    if (
        is_public_application_path
        and not is_upload_path
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

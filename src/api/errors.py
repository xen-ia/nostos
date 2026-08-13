from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "validation_error"
    NOT_FOUND = "not_found"
    TRIP_NOT_FOUND = "trip_not_found"
    RATE_LIMITED = "rate_limited"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    CONFLICT = "conflict"
    INTERNAL_ERROR = "internal_error"


class APIError(Exception):
    def __init__(self, error_code: ErrorCode, detail: str, status_code: int, headers: dict | None = None):
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code
        self.headers = headers


def problem(status_code: int, error_code: ErrorCode, detail: str, request: Request) -> dict:
    return {
        "type": f"https://nostos.dev/problems/{error_code.value}",
        "title": error_code.value,
        "status": status_code,
        "detail": detail,
        "request_id": getattr(request.state, "request_id", None),
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=problem(exc.status_code, exc.error_code, exc.detail, request),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=problem(422, ErrorCode.VALIDATION_ERROR, "Request validation failed", request),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = ErrorCode.NOT_FOUND if exc.status_code == 404 else ErrorCode.INTERNAL_ERROR
        return JSONResponse(
            status_code=exc.status_code,
            content=problem(exc.status_code, code, str(exc.detail), request),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content=problem(500, ErrorCode.INTERNAL_ERROR, "Internal server error", request),
        )

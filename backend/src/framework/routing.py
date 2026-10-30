import logging
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException

from framework.entities import (
    ApplicationError,
    ConfigurationError,
    ConflictError,
    InfrastructureError,
    NotFoundError,
    PayloadTooLargeError,
    ValidationError,
)
from framework.logging import log_context
from framework.messages import ErrorCode, MessageKey
from framework.messages import text as message_text

logger = logging.getLogger("nodekit.http")


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[dict[str, Any]] = Field(default_factory=list)


class ResponseMeta(BaseModel):
    request_id: str


class ApiResponse(BaseModel):
    ok: bool
    data: Any = None
    error: ErrorBody | None = None
    meta: ResponseMeta


class Responses:
    @staticmethod
    def success(data: Any) -> ApiResponse:
        return ApiResponse(
            ok=True, data=data, meta=ResponseMeta(request_id=log_context().get("request_id", ""))
        )

    @staticmethod
    def error(code: str, message: str, status: int, *, details=None, request_id=None):
        result = ApiResponse(
            ok=False,
            error=ErrorBody(code=code, message=message, details=details or []),
            meta=ResponseMeta(request_id=request_id or log_context().get("request_id", "")),
        )
        return JSONResponse(jsonable_encoder(result), status_code=status)


class RouterFactory:
    def create(self, *, prefix: str = "", tags: list[str] | None = None) -> APIRouter:
        return APIRouter(
            prefix=prefix,
            tags=tags or [],
            responses={
                status: {"model": ApiResponse} for status in (403, 404, 409, 413, 422, 500, 502)
            },
        )


class ExceptionHandlers:
    status_by_error = {
        ValidationError: 422,
        NotFoundError: 404,
        ConflictError: 409,
        PayloadTooLargeError: 413,
        InfrastructureError: 502,
        ConfigurationError: 500,
    }

    def install(self, app: FastAPI):
        app.add_exception_handler(ApplicationError, self.application)
        app.add_exception_handler(RequestValidationError, self.validation)
        app.add_exception_handler(HTTPException, self.http)
        app.add_exception_handler(Exception, self.unexpected)

    async def application(self, request: Request, exc: ApplicationError):
        status = next(
            (value for kind, value in self.status_by_error.items() if isinstance(exc, kind)), 500
        )
        return Responses.error(
            exc.code,
            exc.message,
            status,
            details=exc.details,
            request_id=getattr(request.state, "request_id", ""),
        )

    async def validation(self, request: Request, exc: RequestValidationError):
        details = [
            {"field": ".".join(map(str, item["loc"])), "code": item["type"]}
            for item in exc.errors()
        ]
        return Responses.error(
            ErrorCode.VALIDATION_ERROR,
            message_text(MessageKey.REQUEST_VALIDATION_FAILED),
            422,
            details=details,
            request_id=getattr(request.state, "request_id", ""),
        )

    async def http(self, request: Request, exc: HTTPException):
        return Responses.error(
            ErrorCode.NOT_FOUND if exc.status_code == 404 else ErrorCode.HTTP_ERROR,
            message_text(MessageKey.HTTP_NOT_FOUND) if exc.status_code == 404 else str(exc.detail),
            exc.status_code,
            request_id=getattr(request.state, "request_id", ""),
        )

    async def unexpected(self, request: Request, exc: Exception):
        logger.error(
            message_text(MessageKey.UNHANDLED_REQUEST_LOG),
            extra={"error_code": ErrorCode.INTERNAL_ERROR, "error_type": type(exc).__name__},
        )
        return Responses.error(
            ErrorCode.INTERNAL_ERROR,
            message_text(MessageKey.INTERNAL_ERROR),
            500,
            request_id=getattr(request.state, "request_id", ""),
        )

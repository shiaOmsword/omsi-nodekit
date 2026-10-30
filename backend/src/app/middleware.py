import logging
from time import perf_counter

from starlette.middleware.base import BaseHTTPMiddleware

from app.config import ServerSettings
from framework.logging import bind_context
from framework.routing import ExceptionHandlers, Responses
from framework.utils import new_id

logger = logging.getLogger("nodekit.http")


class LocalRequestMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, policy: ServerSettings, errors: ExceptionHandlers):
        super().__init__(app)
        self.policy = policy
        self.errors = errors

    async def dispatch(self, request, call_next):
        request.state.request_id = new_id()
        start = perf_counter()
        with bind_context(request_id=request.state.request_id):
            response = self.reject(request)
            if response is None:
                try:
                    response = await call_next(request)
                except Exception as exc:
                    response = await self.errors.unexpected(request, exc)
            response.headers.update(
                {
                    "X-Request-ID": request.state.request_id,
                    "Cache-Control": "no-store",
                    "X-Content-Type-Options": "nosniff",
                    "Referrer-Policy": "no-referrer",
                }
            )
            logger.info(
                "HTTP request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round((perf_counter() - start) * 1000, 2),
                },
            )
            return response

    def reject(self, request):
        message = None
        if request.url.hostname not in self.policy.allowed_hosts:
            message = "Nodekit accepts configured local hosts only"
        elif request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            if origin and origin not in self.policy.origins():
                message = "Untrusted browser origin"
            elif (
                request.method not in {"GET", "HEAD"}
                and request.headers.get("x-nodekit-request") != "1"
            ):
                message = "Missing X-Nodekit-Request header"
        return Responses.error("forbidden", message, 403) if message else None

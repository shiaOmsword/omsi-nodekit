from contextlib import asynccontextmanager

import punq
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import Settings, get_settings
from app.container import build_container
from app.defaults import APP_TITLE, APP_VERSION
from app.infrastructure.bootstrap import StorageBootstrap
from app.middleware import LocalRequestMiddleware
from app.routes import ApplicationRoutes
from framework.logging import configure_logging
from framework.messages import MessageKey
from framework.messages import text as message_text
from framework.routing import ApiResponse, ExceptionHandlers, Responses
from framework.tasks import TaskScheduler


def create_app(settings: Settings | None = None, *, container: punq.Container | None = None):
    settings = settings or get_settings()
    container = container or build_container(settings)
    container.register(ApplicationRoutes, scope=punq.Scope.singleton)

    @asynccontextmanager
    async def lifespan(application):
        configure_logging(settings.log_level)
        try:
            container.resolve(StorageBootstrap).initialize()
            yield
        finally:
            container.resolve(TaskScheduler).close()

    application = FastAPI(title=APP_TITLE, version=APP_VERSION, lifespan=lifespan)
    application.state.container = container
    errors = container.resolve(ExceptionHandlers)
    errors.install(application)
    application.add_middleware(LocalRequestMiddleware, policy=settings.server, errors=errors)
    application.include_router(container.resolve(ApplicationRoutes).create())
    if settings.frontend_dir.is_dir():
        application.mount(
            "/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend"
        )
    else:

        @application.get("/")
        def frontend_missing() -> ApiResponse:
            return Responses.success(
                {
                    "message": message_text(MessageKey.FRONTEND_BUILD_REQUIRED),
                    "docs": "/docs",
                }
            )

    return application


app = create_app()

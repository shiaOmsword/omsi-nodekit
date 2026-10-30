
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings, get_settings
from app.entities import ConfigRequest, JobRequest, parse_node
from app.execution import MAX_BACKUP, execute, validate_backup
from app.rendering import plan
from app.storage import Store

Action = Literal["check", "doctor", "fresh", "restore", "backup"]


def create_app(settings: Settings | None = None):
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app):
        app.state.store = Store(settings.data_dir)
        app.state.store.recover_jobs()
        app.state.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="nodekit")
        yield
        # Finish active jobs before closing; a reload must not start a second worker.
        app.state.pool.shutdown(wait=True)

    app = FastAPI(title="OMSI Nodekit", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(KeyError)
    async def not_found(request, exc):
        return JSONResponse({"detail": str(exc.args[0])}, status_code=404)

    @app.exception_handler(ValueError)
    async def bad_value(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    def parse(text):
        try:
            return parse_node(text)
        except (ValueError, yaml.YAMLError, RecursionError) as exc:
            raise HTTPException(422, str(exc)) from exc


app = create_app()
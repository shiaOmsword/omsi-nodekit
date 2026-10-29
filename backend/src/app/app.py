from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings, get_settings
from app.entities.node import ConfigRequest, JobRequest, parse_node
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

    @app.middleware("http")
    async def local_requests_only(request: Request, call_next):
        if request.url.hostname not in {"localhost", "127.0.0.1", "::1"}:
            return JSONResponse(
                {"detail": "Nodekit accepts localhost requests only"}, status_code=403
            )
        if request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            if origin and origin not in {
                "http://127.0.0.1:8765",
                "http://localhost:8765",
                "http://127.0.0.1:5173",
                "http://localhost:5173",
            }:
                return JSONResponse({"detail": "Untrusted browser origin"}, status_code=403)
            if (
                request.method not in {"GET", "HEAD"}
                and request.headers.get("x-nodekit-request") != "1"
            ):
                return JSONResponse({"detail": "Missing X-Nodekit-Request header"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

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

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/api/template")
    def template():
        return {"yaml": (Path(__file__).parents[2] / "config" / "config-example.yaml").read_text()}

    @app.post("/api/config/validate")
    def validate(body: ConfigRequest):
        node = parse(body.yaml)
        return {"node": node.model_dump(), "files": plan(node, "check")["files"]}

    @app.get("/api/nodes")
    def nodes(request: Request):
        return request.app.state.store.nodes()

    @app.get("/api/nodes/{node_id}")
    def node(request: Request, node_id: str):
        return request.app.state.store.node(node_id)

    @app.put("/api/nodes/{node_id}")
    def save_node(request: Request, node_id: str, body: ConfigRequest):
        node = parse(body.yaml)
        if node.id != node_id:
            raise HTTPException(422, "URL node ID must match YAML id")
        return request.app.state.store.save_node(node, body.yaml)

    @app.get("/api/nodes/{node_id}/plan")
    def preview(request: Request, node_id: str, action: Action):
        record = request.app.state.store.node(node_id)
        result = plan(parse(record["yaml"]), action)
        result["revision"] = record["revision"]
        return result

    @app.post("/api/nodes/{node_id}/jobs", status_code=202)
    def start_job(request: Request, node_id: str, body: JobRequest):
        store = request.app.state.store
        record = store.node(node_id)
        node = parse(record["yaml"])
        if body.action == "restore":
            if not body.backup_id:
                raise HTTPException(
                    422, "Restore requires an uploaded backup; there is no fresh fallback"
                )
            validate_backup(store.backup_path(body.backup_id).read_bytes())
        elif body.backup_id:
            raise HTTPException(422, "Only restore accepts backup_id")
        try:
            job_id = store.create_job(node_id, body.action, body.revision)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        request.app.state.pool.submit(execute, store, job_id, node, body.action, body.backup_id)
        return store.job(job_id)

    @app.get("/api/jobs")
    def jobs(request: Request):
        return request.app.state.store.jobs()

    @app.get("/api/jobs/{job_id}")
    def job(request: Request, job_id: str):
        return request.app.state.store.job(job_id)

    @app.get("/api/backups")
    def backups(request: Request):
        return request.app.state.store.list_backups()

    @app.post("/api/backups", status_code=201)
    async def upload(request: Request, filename: str = "x-ui.db"):
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > MAX_BACKUP:
                raise HTTPException(413, "Backup exceeds 64 MiB")
        validate_backup(bytes(content))
        filename = filename.replace("\\", "/").rsplit("/", 1)[-1]
        if not filename.endswith(".db") or len(filename) > 100:
            raise HTTPException(422, "Filename must end with .db and be under 100 characters")
        return request.app.state.store.add_backup(bytes(content), filename)

    @app.get("/api/backups/{backup_id}/download")
    def download(request: Request, backup_id: str):
        store = request.app.state.store
        record = store.backup(backup_id)
        return FileResponse(
            store.backup_path(backup_id),
            filename=record["filename"],
            media_type="application/octet-stream",
        )

    @app.get("/api/backups/{backup_id}/manifest")
    def manifest(request: Request, backup_id: str):
        store = request.app.state.store
        store.backup(backup_id)
        path = store.backups / f"{backup_id}.json"
        if not path.is_file():
            raise HTTPException(404, "Imported database has no Nodekit manifest")
        return FileResponse(path, filename="nodekit-manifest.json")

    if settings.frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")
    else:

        @app.get("/")
        def frontend_missing():
            return {
                "message": "Build the frontend: cd frontend && npm ci && npm run build",
                "docs": "/docs",
            }

    return app


app = create_app()

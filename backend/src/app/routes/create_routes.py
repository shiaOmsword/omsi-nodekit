from fastapi import Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from app.config import Limits
from app.defaults import APP_VERSION
from app.entities import ConfigRequest, JobAction, JobRequest
from app.services import BackupService, JobService, NodeService
from framework.entities import PayloadTooLargeError
from framework.messages import MessageKey
from framework.messages import text as message_text
from framework.routing import ApiResponse, Responses, RouterFactory


class ApplicationRoutes:
    """HTTP adapters only: parsing, use-case invocation and response serialization."""

    def __init__(
        self,
        factory: RouterFactory,
        nodes: NodeService,
        jobs: JobService,
        backups: BackupService,
        limits: Limits,
    ):
        self.factory = factory
        self.nodes = nodes
        self.jobs = jobs
        self.backups = backups
        self.limits = limits

    def create(self):
        router = self.factory.create(prefix="/api", tags=["Nodekit"])

        @router.get("/health")
        def health() -> ApiResponse:
            return Responses.success({"status": "ok", "version": APP_VERSION})

        @router.get("/template")
        def template() -> ApiResponse:
            return Responses.success(self.nodes.template())

        @router.post("/config/validate")
        def validate(body: ConfigRequest) -> ApiResponse:
            return Responses.success(self.nodes.validate(body.yaml))

        @router.get("/nodes")
        def nodes() -> ApiResponse:
            return Responses.success(self.nodes.list())

        @router.get("/nodes/{node_id}")
        def node(node_id: str) -> ApiResponse:
            return Responses.success(self.nodes.get(node_id))

        @router.put("/nodes/{node_id}")
        def save_node(node_id: str, body: ConfigRequest) -> ApiResponse:
            return Responses.success(self.nodes.save(node_id, body.yaml))

        @router.get("/nodes/{node_id}/plan")
        def preview(node_id: str, action: JobAction) -> ApiResponse:
            return Responses.success(self.nodes.preview(node_id, action))

        @router.post("/nodes/{node_id}/jobs", status_code=202)
        def start_job(node_id: str, body: JobRequest) -> ApiResponse:
            return Responses.success(
                self.jobs.start(node_id, body.action, body.revision, body.backup_id)
            )

        @router.get("/jobs")
        def jobs() -> ApiResponse:
            return Responses.success(self.jobs.list())

        @router.get("/jobs/{job_id}")
        def job(job_id: str) -> ApiResponse:
            return Responses.success(self.jobs.get(job_id))

        @router.get("/backups")
        def backups() -> ApiResponse:
            return Responses.success(self.backups.list())

        @router.post("/backups", status_code=201)
        async def upload(request: Request, filename: str = "x-ui.db") -> ApiResponse:
            content = bytearray()
            async for chunk in request.stream():
                if len(content) + len(chunk) > self.limits.backup_bytes:
                    raise PayloadTooLargeError(
                        message_text(MessageKey.BACKUP_TOO_LARGE, limit=self.limits.backup_bytes)
                    )
                content.extend(chunk)
            backup = await run_in_threadpool(self.backups.import_backup, bytes(content), filename)
            return Responses.success(backup)

        @router.get("/backups/{backup_id}/download", response_class=FileResponse)
        def download(backup_id: str):
            path, name = self.backups.download(backup_id)
            return FileResponse(path, filename=name, media_type="application/octet-stream")

        @router.get("/backups/{backup_id}/manifest", response_class=FileResponse)
        def manifest(backup_id: str):
            path, name = self.backups.download(backup_id, manifest=True)
            return FileResponse(path, filename=name, media_type="application/json")

        return router

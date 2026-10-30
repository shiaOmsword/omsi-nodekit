from fastapi import Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from app.config import Limits
from app.defaults import APP_VERSION
from app.entities import (
    ConfigRequest,
    DeploymentSelection,
    DiscoverySelection,
    InstallationSelection,
    JobAction,
    JobRequest,
    KeySelection,
    NodeStateRequest,
    SSHKeyRequest,
)
from app.services import BackupService, JobService, NodeService, SSHKeyService
from app.services.discovery_config import DiscoveryConfigService
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
        keys: SSHKeyService,
        discovery_config: DiscoveryConfigService,
    ):
        self.factory = factory
        self.nodes = nodes
        self.jobs = jobs
        self.backups = backups
        self.limits = limits
        self.keys = keys
        self.discovery_config = discovery_config

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

        @router.post("/config/ssh-key")
        def select_key(body: KeySelection) -> ApiResponse:
            return Responses.success(self.nodes.select_key(body.yaml, body.key_id))

        @router.post("/config/installation")
        def select_installation(body: InstallationSelection) -> ApiResponse:
            return Responses.success(self.nodes.select_installation(body.yaml, body.installation))

        @router.post("/config/from-discovery")
        def from_discovery(body: DiscoverySelection) -> ApiResponse:
            return Responses.success(self.discovery_config.suggest(body))

        @router.post("/config/deployment")
        def select_deployment(body: DeploymentSelection) -> ApiResponse:
            return Responses.success(self.nodes.select_deployment(body.yaml, body.target))

        @router.get("/ssh-keys")
        def ssh_keys() -> ApiResponse:
            return Responses.success(self.keys.list())

        @router.post("/ssh-keys", status_code=201)
        def create_key(body: SSHKeyRequest) -> ApiResponse:
            return Responses.success(self.keys.create(body))

        @router.delete("/ssh-keys/{key_id}")
        def delete_key(key_id: str) -> ApiResponse:
            self.keys.delete(key_id)
            return Responses.success({"deleted": True})

        @router.get("/nodes")
        def nodes() -> ApiResponse:
            return Responses.success(self.nodes.list())

        @router.get("/nodes/{node_id}")
        def node(node_id: str) -> ApiResponse:
            return Responses.success(self.nodes.get(node_id))

        @router.put("/nodes/{node_id}")
        def save_node(node_id: str, body: ConfigRequest) -> ApiResponse:
            return Responses.success(self.nodes.save(node_id, body.yaml))

        @router.patch("/nodes/{node_id}/state")
        def set_node_state(node_id: str, body: NodeStateRequest) -> ApiResponse:
            return Responses.success(self.nodes.set_state(node_id, body.state))

        @router.delete("/nodes/{node_id}")
        def delete_node(node_id: str) -> ApiResponse:
            return Responses.success(self.nodes.delete(node_id))

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

from enum import StrEnum

from pydantic import Field, model_validator

from framework.entities import ConflictError, Entity
from framework.messages import MessageKey
from framework.messages import text as message_text
from framework.utils import new_id, sha256, utc_timestamp

from .installation import InstallationReport


class JobAction(StrEnum):
    CHECK = "check"
    DOCTOR = "doctor"
    FRESH = "fresh"
    RESTORE = "restore"
    BACKUP = "backup"
    SYSTEM_BACKUP = "system_backup"
    SYSTEM_RESTORE = "system_restore"
    CONFIGURE = "configure"
    ATTACH_CADDY = "attach_caddy"
    INBOUND = "inbound"
    TRAFFIC = "traffic"
    TCP_TUNING = "tcp_tuning"
    NETWORK_BENCHMARK = "network_benchmark"
    TUNNEL_SETUP = "tunnel_setup"
    TUNNEL_CONTROL = "tunnel_control"
    XRAY = "xray"
    TUNNEL = "tunnel"
    TUNNEL_RESTART = "tunnel_restart"
    TUNNEL_ROUTE = "tunnel_route"
    XHTTP = "xhttp"
    WIREGUARD = "wireguard"
    CLIENT_IMPORT = "client_import"
    SUBSCRIPTION_MAINTENANCE = "subscription_maintenance"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class NodeState(StrEnum):
    ACTIVE = "active"
    HIDDEN = "hidden"
    ARCHIVED = "archived"


class NodeSummary(Entity):
    id: str
    name: str
    revision: str
    state: NodeState = NodeState.ACTIVE


class StoredNode(NodeSummary):
    yaml: str

    @classmethod
    def create(cls, node, text: str):
        return cls(id=node.id, name=node.name, yaml=text, revision=sha256(text))


class Job(Entity):
    id: str = Field(default_factory=new_id)
    node_id: str
    action: JobAction
    status: JobStatus = JobStatus.QUEUED
    created_at: str = Field(default_factory=utc_timestamp)
    finished_at: str | None = None
    backup_id: str | None = None
    error: str | None = None

    @classmethod
    def create(cls, node_id: str, action: JobAction):
        return cls(node_id=node_id, action=action)

    def transition(self, status: JobStatus, *, error=None, backup_id=None):
        allowed = {
            JobStatus.QUEUED: {JobStatus.RUNNING, JobStatus.FAILED, JobStatus.INTERRUPTED},
            JobStatus.RUNNING: {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.INTERRUPTED},
        }
        if status not in allowed.get(self.status, set()):
            raise ConflictError(
                message_text(MessageKey.JOB_TRANSITION_INVALID, current=self.status, target=status)
            )
        return self.model_copy(
            update={
                "status": status,
                "error": error,
                "backup_id": backup_id,
                "finished_at": None if status == JobStatus.RUNNING else utc_timestamp(),
            }
        )


class JobEvent(Entity):
    seq: int | None = None
    job_id: str
    level: str = "info"
    message: str
    created_at: str = Field(default_factory=utc_timestamp)


class JobDetails(Job):
    report: InstallationReport | None = None
    events: list[JobEvent] = Field(default_factory=list)


class Backup(Entity):
    id: str = Field(default_factory=new_id)
    filename: str
    size: int
    sha256: str
    created_at: str = Field(default_factory=utc_timestamp)

    @classmethod
    def create(cls, content: bytes, filename: str):
        return cls(filename=filename, size=len(content), sha256=sha256(content))


class ExecutionEvent(Entity):
    report: InstallationReport | None = None
    message: str | None = None
    level: str = "info"
    backup: bytes | None = None

    @model_validator(mode="after")
    def one_kind(self):
        if sum(value is not None for value in (self.message, self.backup, self.report)) != 1:
            raise ValueError(message_text(MessageKey.EVENT_CONTENT_INVALID))
        if self.level not in {"info", "warning", "error"}:
            raise ValueError(message_text(MessageKey.EVENT_LEVEL_INVALID))
        return self

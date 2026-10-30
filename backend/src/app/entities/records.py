from enum import StrEnum

from pydantic import Field, model_validator

from framework.entities import ConflictError, Entity
from framework.utils import new_id, sha256, utc_timestamp


class JobAction(StrEnum):
    CHECK = "check"
    DOCTOR = "doctor"
    FRESH = "fresh"
    RESTORE = "restore"
    BACKUP = "backup"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class NodeSummary(Entity):
    id: str
    name: str
    revision: str


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
            raise ConflictError(f"Cannot move job from {self.status} to {status}")
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
    message: str | None = None
    level: str = "info"
    backup: bytes | None = None

    @model_validator(mode="after")
    def one_kind(self):
        if (self.message is None) == (self.backup is None):
            raise ValueError("Execution event must contain a message or a backup")
        if self.level not in {"info", "warning", "error"}:
            raise ValueError("Unsupported event level")
        return self

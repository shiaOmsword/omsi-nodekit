from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path

from app.entities import (
    Backup,
    ExecutionEvent,
    Job,
    JobAction,
    JobDetails,
    JobEvent,
    Node,
    NodeSummary,
    StoredNode,
)


class NodeRepository(ABC):
    @abstractmethod
    def save(self, node: StoredNode) -> StoredNode: ...

    @abstractmethod
    def get(self, node_id: str) -> StoredNode: ...

    @abstractmethod
    def list(self) -> list[NodeSummary]: ...


class JobRepository(ABC):
    @abstractmethod
    def enqueue(self, job: Job, revision: str): ...

    @abstractmethod
    def get(self, job_id: str) -> Job: ...

    @abstractmethod
    def details(self, job_id: str) -> JobDetails: ...

    @abstractmethod
    def update(self, job: Job): ...

    @abstractmethod
    def list(self) -> list[Job]: ...

    @abstractmethod
    def append_event(self, event: JobEvent): ...

    @abstractmethod
    def recover(self): ...


class BackupRepository(ABC):
    @abstractmethod
    def save(self, backup: Backup) -> Backup: ...

    @abstractmethod
    def get(self, backup_id: str) -> Backup: ...

    @abstractmethod
    def list(self) -> list[Backup]: ...


class BackupFiles(ABC):
    @abstractmethod
    def write(self, backup_id: str, content: bytes): ...

    @abstractmethod
    def read(self, backup_id: str) -> bytes: ...

    @abstractmethod
    def path(self, backup_id: str, *, manifest: bool = False) -> Path: ...

    @abstractmethod
    def write_manifest(self, backup_id: str, node: Node): ...

    @abstractmethod
    def remove(self, backup_id: str): ...


class BackupValidator(ABC):
    @abstractmethod
    def validate(self, content: bytes): ...


class ArtifactRenderer(ABC):
    @abstractmethod
    def artifacts(self, node: Node) -> dict[str, str]: ...

    @abstractmethod
    def plan(self, node: Node, action: JobAction) -> dict: ...


class NodeExecutor(ABC):
    @abstractmethod
    def execute(
        self, node: Node, action: JobAction, backup: bytes | None
    ) -> Iterator[ExecutionEvent]: ...


class NodeTemplate(ABC):
    @abstractmethod
    def read(self) -> str: ...

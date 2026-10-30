import logging

from app.entities import Job, JobAction, JobEvent, JobStatus, NodeFactory
from app.ports import JobRepository, NodeExecutor, NodeRepository
from framework.entities import ApplicationError, InfrastructureError, ValidationError
from framework.logging import bind_context
from framework.tasks import TaskScheduler

from .backups import BackupService

logger = logging.getLogger("nodekit.jobs")


class ExecuteJob:
    def __init__(self, jobs: JobRepository, executor: NodeExecutor, backups: BackupService):
        self.jobs = jobs
        self.executor = executor
        self.backups = backups

    def run(self, job: Job, node, backup_id: str | None):
        received = None
        with bind_context(job_id=job.id, node_id=node.id):
            try:
                job = job.transition(JobStatus.RUNNING)
                self.jobs.update(job)
                logger.info("Job started")
                content = self.backups.content(backup_id) if backup_id else None
                for event in self.executor.execute(node, job.action, content):
                    if event.backup is not None:
                        if job.action != JobAction.BACKUP or received is not None:
                            raise InfrastructureError("Unexpected backup payload")
                        received = self.backups.import_backup(
                            event.backup, f"{node.id}-x-ui.db", node
                        ).id
                    else:
                        self.jobs.append_event(
                            JobEvent(job_id=job.id, level=event.level, message=event.message)
                        )
                if job.action == JobAction.BACKUP and received is None:
                    raise InfrastructureError("Remote operation returned no backup")
                self.jobs.update(job.transition(JobStatus.SUCCEEDED, backup_id=received))
                logger.info("Job completed")
            except Exception as exc:
                # The application boundary owns persistence of failures; generic exceptions
                # are classified without exposing their values to HTTP or process logs.
                error = (
                    exc
                    if isinstance(exc, ApplicationError)
                    else InfrastructureError("Operation failed unexpectedly")
                )
                self.jobs.append_event(
                    JobEvent(job_id=job.id, level="error", message=error.message)
                )
                self.jobs.update(
                    job.transition(JobStatus.FAILED, error=error.message, backup_id=received)
                )
                logger.error(
                    "Job failed", extra={"error_code": error.code, "error_type": type(exc).__name__}
                )


class JobService:
    def __init__(
        self,
        jobs: JobRepository,
        nodes: NodeRepository,
        factory: NodeFactory,
        backups: BackupService,
        execute: ExecuteJob,
        scheduler: TaskScheduler,
    ):
        self.jobs = jobs
        self.nodes = nodes
        self.factory = factory
        self.backups = backups
        self.execute = execute
        self.scheduler = scheduler

    def start(self, node_id: str, action: JobAction, revision: str, backup_id: str | None):
        stored = self.nodes.get(node_id)
        node = self.factory.from_yaml(stored.yaml)
        if action == JobAction.RESTORE:
            if not backup_id:
                raise ValidationError(
                    "Restore requires an uploaded backup; there is no fresh fallback"
                )
            self.backups.content(backup_id)
        elif backup_id:
            raise ValidationError("Only restore accepts backup_id")
        job = Job.create(node_id, action)
        self.jobs.enqueue(job, revision)
        try:
            self.scheduler.submit(self.execute.run, job, node, backup_id)
        except Exception as exc:
            self.jobs.update(job.transition(JobStatus.FAILED, error="Could not schedule job"))
            raise InfrastructureError("Could not schedule job") from exc
        return self.jobs.details(job.id)

    def list(self):
        return self.jobs.list()

    def get(self, job_id):
        return self.jobs.details(job_id)

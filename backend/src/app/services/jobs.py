import logging

from app.entities import Job, JobAction, JobEvent, JobStatus, NodeFactory
from app.ports import JobRepository, NodeExecutor, NodeRepository
from framework.entities import ApplicationError, InfrastructureError, ValidationError
from framework.logging import bind_context
from framework.messages import MessageKey
from framework.messages import text as message_text
from framework.tasks import TaskScheduler

from .backups import BackupService

logger = logging.getLogger("nodekit.jobs")


class ExecuteJob:
    def __init__(self, jobs: JobRepository, executor: NodeExecutor, backups: BackupService):
        self.jobs = jobs
        self.executor = executor
        self.backups = backups

    def run(self, job: Job, node, backup_id: str | None, options=None):
        received = None
        with bind_context(job_id=job.id, node_id=node.id):
            try:
                job = job.transition(JobStatus.RUNNING)
                self.jobs.update(job)
                logger.info(message_text(MessageKey.JOB_STARTED))
                content = self.backups.content(backup_id) if backup_id else None
                if content is not None and job.action in {
                    JobAction.RESTORE,
                    JobAction.CLIENT_IMPORT,
                    JobAction.WIREGUARD,
                }:
                    from app.system_backup import database_content

                    content = database_content(content, self.backups.limits.backup_bytes)
                execution = (
                    self.executor.execute(node, job.action, content, options)
                    if options
                    else self.executor.execute(node, job.action, content)
                )
                for event in execution:
                    if event.report is not None:
                        self.jobs.save_report(job.id, event.report)
                    elif event.backup is not None:
                        if (
                            job.action not in {JobAction.BACKUP, JobAction.SYSTEM_BACKUP}
                            or received is not None
                        ):
                            raise InfrastructureError(
                                message_text(MessageKey.REMOTE_BACKUP_UNEXPECTED)
                            )
                        received = self.backups.import_backup(
                            event.backup,
                            f"{node.id}.nodekit.zip"
                            if job.action == JobAction.SYSTEM_BACKUP
                            else f"{node.id}-x-ui.db",
                            node,
                        ).id
                    else:
                        self.jobs.append_event(
                            JobEvent(job_id=job.id, level=event.level, message=event.message)
                        )
                if job.action in {JobAction.BACKUP, JobAction.SYSTEM_BACKUP} and received is None:
                    raise InfrastructureError(message_text(MessageKey.REMOTE_BACKUP_MISSING))
                self.jobs.update(job.transition(JobStatus.SUCCEEDED, backup_id=received))
                logger.info(message_text(MessageKey.JOB_COMPLETED))
            except Exception as exc:
                # The application boundary owns persistence of failures; generic exceptions
                # are classified without exposing their values to HTTP or process logs.
                error = (
                    exc
                    if isinstance(exc, ApplicationError)
                    else InfrastructureError(message_text(MessageKey.JOB_UNEXPECTED_FAILURE))
                )
                self.jobs.append_event(
                    JobEvent(job_id=job.id, level="error", message=error.message)
                )
                self.jobs.update(
                    job.transition(JobStatus.FAILED, error=error.message, backup_id=received)
                )
                logger.error(
                    message_text(MessageKey.JOB_FAILED),
                    extra={"error_code": error.code, "error_type": type(exc).__name__},
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

    def start(
        self, node_id: str, action: JobAction, revision: str, backup_id: str | None, options=None
    ):
        stored = self.nodes.get(node_id)
        node = self.factory.from_yaml(stored.yaml)
        if action in {
            JobAction.INBOUND,
            JobAction.TRAFFIC,
            JobAction.TCP_TUNING,
            JobAction.SYSTEM_RESTORE,
            JobAction.NETWORK_BENCHMARK,
            JobAction.TUNNEL_SETUP,
            JobAction.TUNNEL_CONTROL,
            JobAction.XRAY,
            JobAction.TUNNEL,
            JobAction.TUNNEL_RESTART,
            JobAction.TUNNEL_ROUTE,
            JobAction.XHTTP,
            JobAction.WIREGUARD,
            JobAction.CLIENT_IMPORT,
            JobAction.SUBSCRIPTION_MAINTENANCE,
        }:
            expected = str(action)
            if (
                (
                    action
                    not in {
                        JobAction.TCP_TUNING,
                        JobAction.SYSTEM_RESTORE,
                        JobAction.NETWORK_BENCHMARK,
                    }
                    and node.panel.installation != "managed"
                )
                or not options
                or set(options) != {expected}
            ):
                raise ValidationError(
                    message_text(
                        MessageKey.TUNNEL_RESTART_REQUEST_INVALID
                        if action == JobAction.TUNNEL_RESTART
                        else MessageKey.INBOUND_MANAGED_REQUIRED
                    )
                )
        if action == JobAction.TUNNEL_ROUTE:
            route = options["tunnel_route"]
            if route["kind"] == "tunnel" and route["name"] not in {t.name for t in node.tunnels}:
                raise ValidationError(message_text(MessageKey.TUNNEL_ROUTE_INVALID))
        if action in {JobAction.TUNNEL_SETUP, JobAction.TUNNEL_CONTROL}:
            names = options[str(action)].get("names", [])
            if (
                not names
                or len(names) != len(set(names))
                or not set(names) <= {t.name for t in node.tunnels}
            ):
                raise ValidationError(message_text(MessageKey.TUNNEL_CONFIG_INVALID))
        if action == JobAction.TUNNEL_RESTART:
            available = {t.name for t in node.tunnels}
            names = options["tunnel_restart"].get("names", [])
            if not names or len(names) != len(set(names)) or not set(names) <= available:
                raise ValidationError(message_text(MessageKey.TUNNEL_RESTART_REQUEST_INVALID))
        if action == JobAction.TUNNEL:
            available = {t.name for t in node.tunnels}
            tunnel = options["tunnel"]
            if tunnel["name"] not in available or not set(tunnel.get("members", [])) <= available:
                raise ValidationError(message_text(MessageKey.TUNNEL_CONFIG_INVALID))
        if action in {JobAction.FRESH, JobAction.RESTORE} and node.panel.installation != "managed":
            raise ValidationError(message_text(MessageKey.EXISTING_READ_ONLY))
        if action in {JobAction.CONFIGURE, JobAction.ATTACH_CADDY} and (
            node.panel.installation != "managed"
            or not node.deployment
            or node.deployment.caddy_mode != "existing"
        ):
            raise ValidationError(message_text(MessageKey.SUBSCRIPTION_CONFIGURE_GUARD))
        if action in {JobAction.RESTORE, JobAction.CLIENT_IMPORT, JobAction.SYSTEM_RESTORE} or (
            action == JobAction.WIREGUARD and options["wireguard"]["operation"] == "restore"
        ):
            if not backup_id:
                raise ValidationError(message_text(MessageKey.RESTORE_BACKUP_REQUIRED))
            if action == JobAction.RESTORE:
                self.backups.check_restore(node, backup_id)
            elif action == JobAction.WIREGUARD:
                self.backups.wireguard_source(
                    backup_id,
                    options["wireguard"]["source_inbound_id"],
                    options["wireguard"].get("source_ipv6"),
                )
            else:
                self.backups.content(backup_id)
        elif backup_id:
            raise ValidationError(message_text(MessageKey.BACKUP_ONLY_FOR_RESTORE))
        job = Job.create(node_id, action)
        self.jobs.enqueue(job, revision)
        try:
            self.scheduler.submit(self.execute.run, job, node, backup_id, options)
        except Exception as exc:
            self.jobs.update(
                job.transition(JobStatus.FAILED, error=message_text(MessageKey.JOB_SCHEDULE_FAILED))
            )
            raise InfrastructureError(message_text(MessageKey.JOB_SCHEDULE_FAILED)) from exc
        return self.jobs.details(job.id)

    def list(self):
        return self.jobs.list()

    def get(self, job_id):
        return self.jobs.details(job_id)

from app.config import Limits
from app.entities import (
    Backup,
    InstallationReport,
    Job,
    JobDetails,
    JobEvent,
    JobStatus,
    NodeSummary,
    SSHKey,
    StoredNode,
)
from app.ports import BackupRepository, JobRepository, NodeRepository, SSHKeyRepository
from framework.database import SQLiteDatabase
from framework.entities import ConflictError, JsonCodec, NotFoundError
from framework.messages import MessageKey
from framework.messages import text as message_text


class SQLiteNodeRepository(NodeRepository):
    def __init__(self, database: SQLiteDatabase):
        self.database = database

    def save(self, node: StoredNode) -> StoredNode:
        with self.database.connect() as db:
            db.execute(
                "INSERT INTO nodes (id,name,yaml,revision) VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,yaml=excluded.yaml,revision=excluded.revision",
                (node.id, node.name, node.yaml, node.revision),
            )
        return node

    def get(self, node_id: str) -> StoredNode:
        with self.database.connect() as db:
            row = db.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
        if row is None:
            raise NotFoundError(message_text(MessageKey.NODE_NOT_FOUND))
        return StoredNode.model_validate(dict(row))

    def list(self) -> list[NodeSummary]:
        with self.database.connect() as db:
            return [
                NodeSummary.model_validate(dict(row))
                for row in db.execute("SELECT id,name,revision FROM nodes ORDER BY name")
            ]


class SQLiteJobRepository(JobRepository):
    def __init__(self, database: SQLiteDatabase, limits: Limits, codec: JsonCodec):
        self.database = database
        self.limits = limits
        self.codec = codec

    def enqueue(self, job: Job, revision: str):
        with self.database.connect(immediate=True) as db:
            active = db.execute(
                "SELECT 1 FROM jobs WHERE status IN (?,?)", (JobStatus.QUEUED, JobStatus.RUNNING)
            ).fetchone()
            if active:
                raise ConflictError(message_text(MessageKey.JOB_ALREADY_RUNNING))
            row = db.execute("SELECT revision FROM nodes WHERE id=?", (job.node_id,)).fetchone()
            if row is None or row[0] != revision:
                raise ConflictError(message_text(MessageKey.CONFIGURATION_CHANGED))
            db.execute(
                "INSERT INTO jobs (id,node_id,action,status,created_at) VALUES (?,?,?,?,?)",
                (job.id, job.node_id, job.action, job.status, job.created_at),
            )

    def get(self, job_id: str) -> Job:
        with self.database.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise NotFoundError(message_text(MessageKey.JOB_NOT_FOUND))
        return Job.model_validate(dict(row))

    def details(self, job_id: str) -> JobDetails:
        job = self.get(job_id)
        with self.database.connect() as db:
            events = [
                JobEvent.model_validate(dict(row))
                for row in db.execute("SELECT * FROM events WHERE job_id=? ORDER BY seq", (job_id,))
            ]
            row = db.execute("SELECT report FROM job_reports WHERE job_id=?", (job_id,)).fetchone()
        report = InstallationReport.model_validate(self.codec.loads(row[0])) if row else None
        return JobDetails(**job.model_dump(), events=events, report=report)

    def save_report(self, job_id, report):
        with self.database.connect() as db:
            db.execute(
                "INSERT INTO job_reports (job_id,report) VALUES (?,?) "
                "ON CONFLICT(job_id) DO UPDATE SET report=excluded.report",
                (job_id, self.codec.dumps(report.model_dump(mode="json"))),
            )

    def update(self, job: Job):
        with self.database.connect() as db:
            cursor = db.execute(
                "UPDATE jobs SET status=?,error=?,backup_id=?,finished_at=? WHERE id=?",
                (job.status, job.error, job.backup_id, job.finished_at, job.id),
            )
            if not cursor.rowcount:
                raise NotFoundError(message_text(MessageKey.JOB_NOT_FOUND))

    def list(self) -> list[Job]:
        with self.database.connect() as db:
            return [
                Job.model_validate(dict(row))
                for row in db.execute(
                    "SELECT * FROM jobs ORDER BY rowid DESC LIMIT ?", (self.limits.job_history,)
                )
            ]

    def append_event(self, event: JobEvent):
        with self.database.connect() as db:
            db.execute(
                "INSERT INTO events (job_id,level,message,created_at) VALUES (?,?,?,?)",
                (
                    event.job_id,
                    event.level,
                    event.message[: self.limits.event_length],
                    event.created_at,
                ),
            )

    def recover(self):
        with self.database.connect(immediate=True) as db:
            rows = db.execute(
                "SELECT * FROM jobs WHERE status IN (?,?)", (JobStatus.QUEUED, JobStatus.RUNNING)
            ).fetchall()
            for row in rows:
                job = Job.model_validate(dict(row)).transition(
                    JobStatus.INTERRUPTED,
                    error=message_text(MessageKey.JOB_INTERRUPTED),
                )
                db.execute(
                    "UPDATE jobs SET status=?,error=?,finished_at=? WHERE id=?",
                    (job.status, job.error, job.finished_at, job.id),
                )


class SQLiteBackupRepository(BackupRepository):
    def __init__(self, database: SQLiteDatabase):
        self.database = database

    def save(self, backup: Backup) -> Backup:
        with self.database.connect() as db:
            db.execute(
                "INSERT INTO backups (id,filename,size,sha256,created_at) VALUES (?,?,?,?,?)",
                (backup.id, backup.filename, backup.size, backup.sha256, backup.created_at),
            )
        return backup

    def get(self, backup_id: str) -> Backup:
        with self.database.connect() as db:
            row = db.execute("SELECT * FROM backups WHERE id=?", (backup_id,)).fetchone()
        if row is None:
            raise NotFoundError(message_text(MessageKey.BACKUP_NOT_FOUND))
        return Backup.model_validate(dict(row))

    def list(self) -> list[Backup]:
        with self.database.connect() as db:
            return [
                Backup.model_validate(dict(row))
                for row in db.execute("SELECT * FROM backups ORDER BY rowid DESC")
            ]


class SQLiteSSHKeyRepository(SSHKeyRepository):
    def __init__(self, database: SQLiteDatabase):
        self.database = database

    def save(self, key):
        with self.database.connect() as db:
            db.execute(
                "INSERT INTO ssh_keys (id,name,public_key,fingerprint,created_at) VALUES (?,?,?,?,?)",
                (key.id, key.name, key.public_key, key.fingerprint, key.created_at),
            )
        return key

    def get(self, key_id):
        with self.database.connect() as db:
            row = db.execute("SELECT * FROM ssh_keys WHERE id=?", (key_id,)).fetchone()
        if row is None:
            raise NotFoundError(message_text(MessageKey.SSH_KEY_NOT_FOUND))
        return SSHKey.model_validate(dict(row))

    def list(self):
        with self.database.connect() as db:
            return [
                SSHKey.model_validate(dict(row))
                for row in db.execute("SELECT * FROM ssh_keys ORDER BY created_at DESC, id")
            ]

    def delete(self, key_id):
        with self.database.connect() as db:
            db.execute("DELETE FROM ssh_keys WHERE id=?", (key_id,))

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        root.chmod(0o700)
        self.backups = root / "backups"
        self.backups.mkdir(exist_ok=True, mode=0o700)
        self.path = root / "nodekit.db"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS nodes (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, yaml TEXT NOT NULL, revision TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, node_id TEXT NOT NULL, action TEXT NOT NULL,
                    status TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    finished_at TEXT, backup_id TEXT, error TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                    level TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS backups (
                    id TEXT PRIMARY KEY, filename TEXT NOT NULL, size INTEGER NOT NULL,
                    sha256 TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
            """)
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def recover_jobs(self):
        with self.connect() as db:
            db.execute(
                "UPDATE jobs SET status='interrupted', error='Local backend restarted; check remote services before retrying', finished_at=CURRENT_TIMESTAMP WHERE status IN ('queued','running')"
            )

    def save_node(self, node, text):
        revision = hashlib.sha256(text.encode()).hexdigest()
        with self.connect() as db:
            db.execute(
                "INSERT INTO nodes VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,yaml=excluded.yaml,revision=excluded.revision",
                (node.id, node.name, text, revision),
            )
        return self.node(node.id)

    def node(self, node_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
        if not row:
            raise KeyError("Node not found")
        return dict(row)

    def nodes(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT id,name,revision FROM nodes ORDER BY name")]

    def create_job(self, node_id, action, revision):
        job_id = uuid4().hex
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM jobs WHERE status IN ('queued','running')").fetchone():
                raise ValueError("Another operation is running; wait for it to finish")
            row = db.execute("SELECT revision FROM nodes WHERE id=?", (node_id,)).fetchone()
            if not row or row[0] != revision:
                raise ValueError("Configuration changed; refresh and preview the plan again")
            db.execute(
                "INSERT INTO jobs (id,node_id,action,status) VALUES (?,?,?,'queued')",
                (job_id, node_id, action),
            )
        return job_id

    def event(self, job_id, message, level="info"):
        with self.connect() as db:
            db.execute(
                "INSERT INTO events (job_id,level,message) VALUES (?,?,?)",
                (job_id, level, message[:5000]),
            )

    def finish(self, job_id, status, error=None, backup_id=None):
        with self.connect() as db:
            db.execute(
                "UPDATE jobs SET status=?,error=?,backup_id=?,finished_at=CURRENT_TIMESTAMP WHERE id=?",
                (status, error, backup_id, job_id),
            )

    def start(self, job_id):
        with self.connect() as db:
            db.execute("UPDATE jobs SET status='running' WHERE id=?", (job_id,))

    def jobs(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM jobs ORDER BY rowid DESC LIMIT 50")]

    def job(self, job_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise KeyError("Job not found")
            result = dict(row)
            result["events"] = [
                dict(r)
                for r in db.execute("SELECT * FROM events WHERE job_id=? ORDER BY seq", (job_id,))
            ]
        return result

    def add_backup(self, raw: bytes, filename: str):
        backup_id = uuid4().hex
        path = self.backups / f"{backup_id}.db"
        path.write_bytes(raw)
        path.chmod(0o600)
        with self.connect() as db:
            db.execute(
                "INSERT INTO backups (id,filename,size,sha256) VALUES (?,?,?,?)",
                (backup_id, filename, len(raw), hashlib.sha256(raw).hexdigest()),
            )
        return self.backup(backup_id)

    def backup(self, backup_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM backups WHERE id=?", (backup_id,)).fetchone()
        if not row:
            raise KeyError("Backup not found")
        return dict(row)

    def list_backups(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM backups ORDER BY rowid DESC")]

    def backup_path(self, backup_id):
        self.backup(backup_id)
        return self.backups / f"{backup_id}.db"

    def save_manifest(self, backup_id, node):
        path = self.backups / f"{backup_id}.json"
        path.write_text(json.dumps(node.model_dump(), indent=2))
        os.chmod(path, 0o600)

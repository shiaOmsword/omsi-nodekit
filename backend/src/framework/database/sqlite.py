"""SQLite infrastructure. This module knows no application tables or entities."""

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from framework.messages import MessageKey
from framework.messages import text as message_text


@dataclass(frozen=True)
class Migration:
    version: int
    sql: str


class SQLiteDatabase:
    def __init__(self, path: Path, timeout: float = 10):
        self.path = path
        self.timeout = timeout

    def initialize(self, migrations: list[Migration]):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path.parent.chmod(0o700)
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if migrations and version > max(m.version for m in migrations):
                raise RuntimeError(message_text(MessageKey.SQLITE_SCHEMA_NEWER))
            for migration in sorted(migrations, key=lambda item: item.version):
                if migration.version > version:
                    db.executescript(
                        f"BEGIN IMMEDIATE;\n{migration.sql}\nPRAGMA user_version={migration.version};\nCOMMIT;"
                    )
        self.path.chmod(0o600)

    @contextmanager
    def connect(self, *, immediate: bool = False):
        db = sqlite3.connect(self.path, timeout=self.timeout)
        db.row_factory = sqlite3.Row
        try:
            with db:
                db.execute("PRAGMA foreign_keys=ON")
                if immediate:
                    db.execute("BEGIN IMMEDIATE")
                yield db
        finally:
            db.close()

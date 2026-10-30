"""Standard-library-only helpers, also packaged into the remote SSH agent."""

import os
import sqlite3
from contextlib import closing
from pathlib import Path

from framework.messages import MessageKey
from framework.messages import text as message_text


class SQLiteSnapshots:
    def validate(self, path, *, tables=(), columns=None):
        with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as db:
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError(message_text(MessageKey.SQLITE_INTEGRITY_FAILED))
            existing = {
                row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if not set(tables) <= existing:
                raise ValueError(message_text(MessageKey.SQLITE_TABLES_MISSING))
            for table, required in (columns or {}).items():
                if not table.replace("_", "").isalnum():
                    raise ValueError(message_text(MessageKey.SQLITE_IDENTIFIER_INVALID))
                actual = {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}
                if not set(required) <= actual:
                    raise ValueError(message_text(MessageKey.SQLITE_SCHEMA_UNSUPPORTED))

    def snapshot(self, source, destination):
        with closing(
            sqlite3.connect(Path(source).resolve().as_uri() + "?mode=ro", uri=True)
        ) as src:
            with closing(sqlite3.connect(destination)) as dst, dst:
                src.backup(dst)
        os.chmod(destination, 0o600)

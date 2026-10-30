"""Standard-library-only helpers, also packaged into the remote SSH agent."""

import os
import sqlite3
from contextlib import closing
from pathlib import Path


class SQLiteSnapshots:
    def validate(self, path, *, tables=(), columns=None):
        with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as db:
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("SQLite integrity check failed")
            existing = {
                row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if not set(tables) <= existing:
                raise ValueError("Required SQLite tables are missing")
            for table, required in (columns or {}).items():
                if not table.replace("_", "").isalnum():
                    raise ValueError("Invalid schema identifier")
                actual = {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}
                if not set(required) <= actual:
                    raise ValueError("Unsupported SQLite schema")

    def snapshot(self, source, destination):
        with closing(
            sqlite3.connect(Path(source).resolve().as_uri() + "?mode=ro", uri=True)
        ) as src:
            with closing(sqlite3.connect(destination)) as dst, dst:
                src.backup(dst)
        os.chmod(destination, 0o600)

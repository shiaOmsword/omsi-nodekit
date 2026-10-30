import sqlite3
import tempfile
from pathlib import Path

from app.config import Limits
from app.defaults import XUI_SETTINGS_COLUMNS, XUI_TABLES
from app.ports import BackupFiles, BackupValidator
from framework.database import SQLiteSnapshots
from framework.entities import JsonCodec, NotFoundError, PayloadTooLargeError, ValidationError
from framework.messages import MessageKey
from framework.messages import text as message_text
from framework.utils import PrivateFiles


class XuiBackupValidator(BackupValidator):
    def __init__(self, snapshots: SQLiteSnapshots, limits: Limits):
        self.snapshots = snapshots
        self.limits = limits

    def validate(self, content: bytes):
        if len(content) > self.limits.backup_bytes:
            raise PayloadTooLargeError(
                message_text(MessageKey.BACKUP_TOO_LARGE, limit=self.limits.backup_bytes)
            )
        if not content.startswith(b"SQLite format 3\x00"):
            raise ValidationError(message_text(MessageKey.BACKUP_SQLITE_REQUIRED))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "snapshot.db"
            path.write_bytes(content)
            try:
                self.snapshots.validate(
                    path,
                    tables=XUI_TABLES,
                    columns=XUI_SETTINGS_COLUMNS,
                )
            except (sqlite3.DatabaseError, ValueError) as exc:
                raise ValidationError(message_text(MessageKey.BACKUP_SQLITE_INVALID)) from exc


class LocalBackupFiles(BackupFiles):
    def __init__(self, files: PrivateFiles, codec: JsonCodec):
        self.files = files
        self.codec = codec

    def write(self, backup_id, content):
        return self.files.write(f"{backup_id}.db", content)

    def read(self, backup_id):
        return self.path(backup_id).read_bytes()

    def path(self, backup_id, *, manifest=False):
        path = self.files.path(f"{backup_id}.json" if manifest else f"{backup_id}.db")
        if not path.is_file():
            raise NotFoundError(
                message_text(MessageKey.BACKUP_MANIFEST_MISSING)
                if manifest
                else message_text(MessageKey.BACKUP_FILE_MISSING)
            )
        return path

    def write_manifest(self, backup_id, node):
        self.files.write(
            f"{backup_id}.json",
            self.codec.dumps(node.model_dump(mode="json"), pretty=True).encode(),
        )

    def remove(self, backup_id):
        self.files.path(f"{backup_id}.db").unlink(missing_ok=True)
        self.files.path(f"{backup_id}.json").unlink(missing_ok=True)

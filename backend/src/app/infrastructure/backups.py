import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from app.backup_clients import public_catalog, read_catalog
from app.backup_wireguard import key_bytes
from app.config import Limits
from app.defaults import XUI_READ_DEFAULTS, XUI_SETTINGS_COLUMNS, XUI_TABLES
from app.entities.panel import Panel
from app.ports import BackupFiles, BackupValidator
from app.system_backup import database_content
from app.wg_easy import TABLES as WG_EASY_TABLES
from app.wg_easy import read_wg_easy
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
        system_archive = content.startswith(b"PK")
        if system_archive:
            try:
                content = database_content(content, self.limits.backup_bytes)
            except ValueError as exc:
                raise ValidationError(message_text(MessageKey.SYSTEM_BACKUP_INVALID)) from exc
        if not content.startswith(b"SQLite format 3\x00"):
            raise ValidationError(message_text(MessageKey.BACKUP_SQLITE_REQUIRED))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "snapshot.db"
            path.write_bytes(content)
            try:
                self.snapshots.validate(path)
                with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
                    tables = {
                        r[0]
                        for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    }
                if WG_EASY_TABLES <= tables:
                    if "inbounds" in tables or system_archive:
                        raise ValueError()
                    for source in read_wg_easy(path):
                        identities = [
                            (source["settings"]["secretKey"], source["server_public_key"])
                        ]
                        identities += [
                            (c["privateKey"], c["publicKey"])
                            for c in source["clients"]
                            if c.get("privateKey")
                        ]
                        for private, public in identities:
                            derived = (
                                X25519PrivateKey.from_private_bytes(key_bytes(private))
                                .public_key()
                                .public_bytes_raw()
                            )
                            if derived != key_bytes(public):
                                raise ValueError()
                    return
                self.snapshots.validate(
                    path,
                    tables=XUI_TABLES,
                    columns=XUI_SETTINGS_COLUMNS,
                )
            except (sqlite3.DatabaseError, ValueError) as exc:
                raise ValidationError(message_text(MessageKey.BACKUP_SQLITE_INVALID)) from exc

    def clients(self, content: bytes) -> dict:
        with tempfile.TemporaryDirectory(prefix="nodekit-clients-") as folder:
            source = Path(folder) / "source.db"
            source.write_bytes(content)
            try:
                return public_catalog(read_catalog(source))
            except (sqlite3.DatabaseError, ValueError, TypeError, KeyError) as exc:
                raise ValidationError(message_text(MessageKey.BACKUP_CLIENTS_INVALID)) from exc

    def restore_profile(self, content: bytes) -> dict:
        with tempfile.TemporaryDirectory(prefix="nodekit-restore-profile-") as folder:
            source = Path(folder) / "source.db"
            source.write_bytes(content)
            try:
                self.snapshots.validate(source, tables=XUI_TABLES, columns=XUI_SETTINGS_COLUMNS)
                with closing(
                    sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
                ) as db:
                    settings = dict(
                        db.execute(
                            "SELECT key,value FROM settings WHERE key IN (?,?)",
                            ("webBasePath", "subPath"),
                        )
                    )
                return {
                    "base_path": Panel.safe_url_path(
                        settings.get("webBasePath", XUI_READ_DEFAULTS["webBasePath"])
                    ),
                    "subscription_path": Panel.safe_url_path(
                        settings.get("subPath", XUI_READ_DEFAULTS["subPath"])
                    ),
                }
            except (sqlite3.DatabaseError, ValueError, TypeError) as exc:
                raise ValidationError(message_text(MessageKey.RESTORE_PROFILE_INVALID)) from exc


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
            self.codec.dumps(node.export_config(), pretty=True).encode(),
        )

    def remove(self, backup_id):
        self.files.path(f"{backup_id}.db").unlink(missing_ok=True)
        self.files.path(f"{backup_id}.json").unlink(missing_ok=True)

from app.config import Limits
from app.entities import Backup, Node
from app.ports import BackupFiles, BackupRepository, BackupValidator
from framework.entities import NotFoundError, ValidationError
from framework.messages import MessageKey
from framework.messages import text as message_text
from framework.utils import sha256


class BackupService:
    def __init__(
        self,
        backups: BackupRepository,
        files: BackupFiles,
        validator: BackupValidator,
        limits: Limits,
    ):
        self.backups = backups
        self.files = files
        self.validator = validator
        self.limits = limits

    def import_backup(self, content: bytes, filename: str, node: Node | None = None) -> Backup:
        filename = filename.replace("\\", "/").rsplit("/", 1)[-1]
        if (
            not filename.endswith(".db")
            or len(filename) > self.limits.filename_length
            or any(ord(c) < 32 for c in filename)
        ):
            raise ValidationError(message_text(MessageKey.BACKUP_FILENAME_INVALID))
        self.validator.validate(content)
        backup = Backup.create(content, filename)
        self.files.write(backup.id, content)
        try:
            if node is not None:
                self.files.write_manifest(backup.id, node)
            return self.backups.save(backup)
        except Exception:
            self.files.remove(backup.id)
            raise

    def list(self):
        return self.backups.list()

    def content(self, backup_id: str) -> bytes:
        metadata = self.backups.get(backup_id)
        try:
            content = self.files.read(backup_id)
        except FileNotFoundError as exc:
            raise NotFoundError(message_text(MessageKey.BACKUP_FILE_MISSING)) from exc
        if sha256(content) != metadata.sha256:
            raise ValidationError(message_text(MessageKey.BACKUP_CHECKSUM_INVALID))
        self.validator.validate(content)
        return content

    def download(self, backup_id: str, *, manifest=False):
        metadata = self.backups.get(backup_id)
        path = self.files.path(backup_id, manifest=manifest)
        return path, "nodekit-manifest.json" if manifest else metadata.filename

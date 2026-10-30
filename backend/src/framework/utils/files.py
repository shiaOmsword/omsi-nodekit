import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from framework.messages import MessageKey
from framework.messages import text as message_text


class PrivateFiles:
    def __init__(self, root: Path):
        self.root = root

    def initialize(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)

    def path(self, name: str) -> Path:
        if not name or name in {".", ".."} or any(c in name for c in ("/", "\\", "\x00")):
            raise ValueError(message_text(MessageKey.MANAGED_FILENAME_INVALID))
        path = self.root / name
        if path.is_symlink():
            raise ValueError(message_text(MessageKey.MANAGED_SYMLINK_FORBIDDEN))
        return path

    def write(self, name: str, content: bytes) -> Path:
        self.initialize()
        path = self.path(name)
        temporary = None
        try:
            with NamedTemporaryFile(dir=self.root, delete=False) as output:
                temporary = Path(output.name)
                output.write(content)
            temporary.chmod(0o600)
            os.replace(temporary, path)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()
        return path

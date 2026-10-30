"""Local OpenSSH key generation; private material never leaves this directory."""

import csv
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from framework.messages import MessageKey
from framework.messages import text as message_text

from .execute import CommandRunner, ProcessError


@dataclass(frozen=True)
class KeyOptions:
    directory: Path
    binary: str = "ssh-keygen"
    timeout: int = 30


class OpenSSHKeys:
    def __init__(self, runner: CommandRunner, options: KeyOptions):
        self.runner = runner
        self.options = options

    def _restrict(self, path: Path, *, directory=False):
        try:
            if os.name == "nt":
                # Resolve the SID rather than a localized Windows user/group name.
                identity = self.runner.run(
                    ["whoami", "/user", "/fo", "csv", "/nh"],
                    timeout=self.options.timeout,
                    sensitive=True,
                )
                sid = next(csv.reader([identity]))[-1]
                if not re.fullmatch(r"S-1-[0-9-]+", sid):
                    raise ProcessError(message_text(MessageKey.SSH_KEY_PERMISSION_FAILED))
                access = f"*{sid}:" + ("(OI)(CI)F" if directory else "F")
                self.runner.run(
                    ["icacls", str(path), "/inheritance:r", "/grant:r", access],
                    timeout=self.options.timeout,
                    sensitive=True,
                )
            else:
                path.chmod(0o700 if directory else 0o600)
        except (OSError, ValueError, StopIteration, ProcessError) as exc:
            raise ProcessError(message_text(MessageKey.SSH_KEY_PERMISSION_FAILED)) from exc

    def _root(self):
        root = self.options.directory
        if root.is_symlink() or (root.exists() and not root.is_dir()):
            raise ProcessError(message_text(MessageKey.SSH_KEY_STORAGE_INVALID))
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._restrict(root, directory=True)
        return root

    def _directory(self, key_id):
        if not re.fullmatch(r"[a-f0-9]{32}", key_id):
            raise ProcessError(message_text(MessageKey.SSH_KEY_ID_INVALID))
        path = self.options.directory / key_id
        if path.is_symlink():
            raise ProcessError(message_text(MessageKey.SSH_KEY_STORAGE_INVALID))
        return path

    def generate(self, key_id: str) -> tuple[str, str]:
        root = self._root()
        destination = self._directory(key_id)
        if destination.exists():
            raise ProcessError(message_text(MessageKey.SSH_KEY_GENERATION_FAILED))
        with tempfile.TemporaryDirectory(prefix=".new-", dir=root) as temporary:
            folder = Path(temporary)
            self._restrict(folder, directory=True)
            identity = folder / "id_ed25519"
            try:
                self.runner.run(
                    [
                        self.options.binary,
                        "-q",
                        "-t",
                        "ed25519",
                        "-N",
                        "",
                        "-C",
                        f"nodekit-{key_id}",
                        "-f",
                        str(identity),
                    ],
                    timeout=self.options.timeout,
                    sensitive=True,
                )
                self._restrict(identity)
                self._restrict(identity.with_suffix(".pub"))
                public = identity.with_suffix(".pub").read_text(encoding="utf-8").strip()
                parts = public.split()
                if len(parts) != 3 or parts[0] != "ssh-ed25519":
                    raise ProcessError(message_text(MessageKey.SSH_KEY_GENERATION_FAILED))
                fingerprint = self.runner.run(
                    [
                        self.options.binary,
                        "-l",
                        "-E",
                        "sha256",
                        "-f",
                        str(identity.with_suffix(".pub")),
                    ],
                    timeout=self.options.timeout,
                    sensitive=True,
                ).split()[1]
                if not fingerprint.startswith("SHA256:"):
                    raise ProcessError(message_text(MessageKey.SSH_KEY_GENERATION_FAILED))
                # Move the complete pair atomically. TemporaryDirectory removes only its old path.
                folder.rename(destination)
            except (OSError, IndexError, ProcessError) as exc:
                raise ProcessError(message_text(MessageKey.SSH_KEY_GENERATION_FAILED)) from exc
        return public, fingerprint

    def identity(self, key_id: str) -> Path:
        self._root()
        directory = self._directory(key_id)
        path = directory / "id_ed25519"
        if path.is_symlink() or not path.is_file():
            raise ProcessError(message_text(MessageKey.SSH_KEY_FILE_MISSING))
        self._restrict(directory, directory=True)
        self._restrict(path)
        return path.resolve()

    def remove(self, key_id: str):
        directory = self._directory(key_id)
        if directory.exists():
            shutil.rmtree(directory)

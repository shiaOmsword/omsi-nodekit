"""Pinned, digest-checked native releases; no remote shell installers."""

import hashlib
import platform
import shutil
import tarfile
import urllib.request
from pathlib import Path, PurePosixPath

from app.defaults import NATIVE_RELEASE
from framework.messages import MessageKey
from framework.messages import text as message_text


def architecture():
    value = {"x86_64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine())
    if value is None:
        raise RuntimeError(message_text(MessageKey.DEPLOYMENT_RELEASE_INVALID))
    return value


class NativeRelease:
    def __init__(self, context):
        self.context = context

    @staticmethod
    def unpack(archive, destination):
        with tarfile.open(archive, "r:gz") as bundle:
            members = bundle.getmembers()
            total = 0
            for member in members:
                path = PurePosixPath(member.name)
                total += member.size
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or not path.parts
                    or path.parts[0] != "x-ui"
                    or not (member.isfile() or member.isdir())
                    or total > NATIVE_RELEASE["unpacked_bytes"]
                    or len(members) > 20000
                ):
                    raise RuntimeError(message_text(MessageKey.DEPLOYMENT_RELEASE_INVALID))
            # Validate the entire archive before writing any extracted member.
            for member in members:
                relative = PurePosixPath(member.name).relative_to("x-ui")
                target = destination.joinpath(*relative.parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True, mode=0o700)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    with bundle.extractfile(member) as source, target.open("xb") as output:
                        shutil.copyfileobj(source, output)
                    target.chmod(0o700 if member.mode & 0o111 else 0o600)

    def install(self, base):
        arch = architecture()
        url = f"{NATIVE_RELEASE['repository']}/x-ui-linux-{arch}.tar.gz"
        archive = base / "release.tar.gz"
        digest = hashlib.sha256()
        count = 0
        request = urllib.request.Request(url, headers={"User-Agent": "omsi-nodekit"})
        with urllib.request.urlopen(request, timeout=self.context.policy["pull_timeout"]) as source:
            with archive.open("xb") as output:
                while block := source.read(1024 * 1024):
                    count += len(block)
                    if count > NATIVE_RELEASE["archive_bytes"]:
                        raise RuntimeError(message_text(MessageKey.DEPLOYMENT_RELEASE_INVALID))
                    digest.update(block)
                    output.write(block)
        if digest.hexdigest() != NATIVE_RELEASE["sha256"][arch]:
            raise RuntimeError(message_text(MessageKey.DEPLOYMENT_RELEASE_INVALID))
        self.unpack(archive, base / "runtime")
        binary = base / "runtime" / "x-ui"
        if not binary.is_file():
            raise RuntimeError(message_text(MessageKey.DEPLOYMENT_RELEASE_INVALID))
        archive.unlink()
        self.context.emit(message_text(MessageKey.DEPLOYMENT_NATIVE_INSTALLED))
        return binary

    def command(self, base):
        return [
            "env",
            f"XUI_DB_FOLDER={base}/db",
            "XUI_DB_TYPE=sqlite",
            f"XUI_BIN_FOLDER={base}/runtime/bin",
            f"XUI_LOG_FOLDER={base}/logs",
            str(Path(base) / "runtime" / "x-ui"),
        ]

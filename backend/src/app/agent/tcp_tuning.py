"""Read and manage the VPS default TCP congestion algorithm.

Only explicitly owned sysctl/modules-load files may be modified. Active TCP
connections and systemd SSH services are deliberately left untouched.
"""

import hashlib
import os
import tempfile
from pathlib import Path

from framework.messages import MessageKey
from framework.messages import text as message_text

HEADER = b"# Managed by OMSI Nodekit; do not edit manually.\n"
SYSCTL_CONTENT = {
    name: HEADER + f"net.ipv4.tcp_congestion_control = {name}\n".encode("ascii")
    for name in ("cubic", "bbr")
}
MODULE_CONTENT = HEADER + b"tcp_bbr\n"


class TCPConfigurator:
    def __init__(
        self,
        context,
        *,
        current_path=Path("/proc/sys/net/ipv4/tcp_congestion_control"),
        available_path=Path("/proc/sys/net/ipv4/tcp_available_congestion_control"),
        sysctl_path=Path("/etc/sysctl.d/99-zz-omsi-nodekit-tcp.conf"),
        module_path=Path("/etc/modules-load.d/omsi-nodekit-tcp.conf"),
    ):
        self.context = context
        self.current_path = Path(current_path)
        self.available_path = Path(available_path)
        self.sysctl_path = Path(sysctl_path)
        self.module_path = Path(module_path)

    @staticmethod
    def _read_owned(path, permitted):
        """Return bytes and collision flag without following foreign symlinks."""
        if path.is_symlink() or (path.exists() and not path.is_file()):
            return None, True
        if not path.exists():
            return None, False
        data = path.read_bytes()
        return data, data not in permitted

    def inspect(self):
        try:
            current = self.current_path.read_text(encoding="ascii").strip()
            available = self.available_path.read_text(encoding="ascii").split()
            config, config_conflict = self._read_owned(self.sysctl_path, SYSCTL_CONTENT.values())
            module, module_conflict = self._read_owned(self.module_path, (MODULE_CONTENT,))
        except OSError:
            return None
        configured = next((name for name, data in SYSCTL_CONTENT.items() if config == data), None)
        digest = hashlib.sha256()
        for value in (
            current.encode("ascii"),
            " ".join(available).encode("ascii"),
            config if config is not None else b"<absent>",
            module if module is not None else b"<absent>",
            str(config_conflict).encode("ascii"),
            str(module_conflict).encode("ascii"),
        ):
            digest.update(len(value).to_bytes(8, "big"))
            digest.update(value)
        return {
            "current": current,
            "available": available,
            "managed_algorithm": configured,
            "conflict": config_conflict or module_conflict,
            "fingerprint": digest.hexdigest(),
        }

    @staticmethod
    def _replace(path, expected, proposed):
        """Compare before replacing: never overwrite another operator's edits."""
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise RuntimeError(message_text(MessageKey.TCP_TUNING_CONFLICT))
        actual = path.read_bytes() if path.exists() else None
        if actual != expected:
            raise RuntimeError(message_text(MessageKey.TCP_TUNING_STALE))
        if proposed is None:
            if path.exists():
                path.unlink()
            return
        if not path.parent.is_dir():
            raise RuntimeError(message_text(MessageKey.TCP_TUNING_CONFLICT))
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=".nodekit-tcp-", dir=path.parent, delete=False
            ) as stream:
                temp_name = stream.name
                stream.write(proposed)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temp_name, 0o644)
            os.replace(temp_name, path)
        finally:
            if temp_name is not None and os.path.exists(temp_name):
                os.unlink(temp_name)

    def apply(self):
        options = (self.context.payload.get("options") or {}).get("tcp_tuning") or {}
        target = options.get("algorithm")
        if target not in SYSCTL_CONTENT:
            raise RuntimeError(message_text(MessageKey.TCP_TUNING_REQUEST_INVALID))
        before = self.inspect()
        if before is None:
            raise RuntimeError(message_text(MessageKey.TCP_TUNING_UNAVAILABLE))
        if before["fingerprint"] != options.get("expected_fingerprint"):
            raise RuntimeError(message_text(MessageKey.TCP_TUNING_STALE))
        if before["conflict"]:
            raise RuntimeError(message_text(MessageKey.TCP_TUNING_CONFLICT))
        old_config, _ = self._read_owned(self.sysctl_path, SYSCTL_CONTENT.values())
        old_module, _ = self._read_owned(self.module_path, (MODULE_CONTENT,))
        changes = []
        try:
            if target == "bbr" and "bbr" not in before["available"]:
                self.context.command(["modprobe", "tcp_bbr"])
                if target not in self.available_path.read_text(encoding="ascii").split():
                    raise RuntimeError(message_text(MessageKey.TCP_TUNING_UNAVAILABLE))
            desired = (
                (self.sysctl_path, old_config, SYSCTL_CONTENT[target]),
                (self.module_path, old_module, MODULE_CONTENT if target == "bbr" else None),
            )
            for path, original, replacement in desired:
                if original != replacement:
                    self._replace(path, original, replacement)
                    changes.append((path, original, replacement))
            self.context.command(["sysctl", "-w", f"net.ipv4.tcp_congestion_control={target}"])
            after = self.inspect()
            if not after or after["current"] != target or after["managed_algorithm"] != target:
                raise RuntimeError(message_text(MessageKey.TCP_TUNING_FAILED))
        except Exception as exc:
            for path, original, replacement in reversed(changes):
                try:
                    self._replace(path, replacement, original)
                except Exception:
                    self.context.emit(message_text(MessageKey.DEPLOYMENT_ROLLBACK_FAILED), "error")
            try:
                if self.current_path.read_text(encoding="ascii").strip() != before["current"]:
                    self.context.command(
                        ["sysctl", "-w", f"net.ipv4.tcp_congestion_control={before['current']}"]
                    )
            except Exception:
                self.context.emit(message_text(MessageKey.DEPLOYMENT_ROLLBACK_FAILED), "error")
            raise RuntimeError(message_text(MessageKey.TCP_TUNING_FAILED)) from exc
        self.context.emit(message_text(MessageKey.TCP_TUNING_APPLIED, algorithm=target))

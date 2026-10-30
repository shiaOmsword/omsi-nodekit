"""Read-only OS/container metadata. Never start, restart or reconfigure a service."""

import json
import shlex
import shutil
from pathlib import Path, PurePosixPath

from framework.messages import MessageKey
from framework.messages import text as message_text


class SystemInventory:
    def __init__(self, context):
        self.context = context
        self.policy = context.discovery
        self.maximum = self.policy["metadata_bytes"]
        self.warnings = []

    def command(self, args):
        result = self.context.runner.completed(args, timeout=self.context.policy["command_timeout"])
        if result.returncode or len(result.stdout.encode("utf-8")) > self.maximum:
            raise RuntimeError(message_text(MessageKey.INSPECTION_UNAVAILABLE))
        return result.stdout

    def service(self, name):
        if not shutil.which("systemctl"):
            return {}
        try:
            raw = self.command(
                [
                    "systemctl",
                    "show",
                    name,
                    "--no-pager",
                    "--property=LoadState,ActiveState,MainPID,ExecStart,WorkingDirectory,Environment,EnvironmentFiles",
                ]
            )
            values = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
            return values if values.get("LoadState") not in {None, "not-found"} else {}
        except RuntimeError:
            self.warnings.append(message_text(MessageKey.INSPECTION_UNAVAILABLE))
            return {}

    def containers(self):
        if not shutil.which("docker"):
            return []
        try:
            ids = self.command(["docker", "ps", "-aq", "--no-trunc"]).split()
            maximum = self.policy["max_containers"]
            if len(ids) > maximum:
                self.warnings.append(message_text(MessageKey.INSPECTION_TOO_LARGE))
            # Inspect separately to avoid unbounded multi-container JSON and command lengths.
            result = []
            for identifier in ids[:maximum]:
                try:
                    item = json.loads(self.command(["docker", "inspect", identifier]))[0]
                    result.append(item)
                except (RuntimeError, ValueError, IndexError, TypeError):
                    self.warnings.append(message_text(MessageKey.INSPECTION_DOCKER_FAILED))
            return result
        except RuntimeError:
            self.warnings.append(message_text(MessageKey.INSPECTION_DOCKER_FAILED))
            return []

    def environment(self, service, files=()):
        """Read only DB location/type. Do not source shell code or return credentials."""
        allowed = {"XUI_DB_FOLDER", "XUI_DB_TYPE"}
        values = {}
        for name in files:
            path = Path(name)
            try:
                if path.is_file() and path.stat().st_size <= self.maximum:
                    for line in path.read_text(encoding="utf-8").splitlines():
                        parts = shlex.split(line, comments=True)
                        if parts and parts[0] == "export":
                            parts = parts[1:]
                        for part in parts:
                            key, separator, value = part.partition("=")
                            if separator and key in allowed:
                                values[key] = value
            except (OSError, ValueError, UnicodeError):
                self.warnings.append(message_text(MessageKey.INSPECTION_UNAVAILABLE))
        for item in shlex.split(service.get("Environment", "")):
            key, separator, value = item.partition("=")
            if separator and key in allowed:
                values[key] = value
        # The running process has the effective environment, including systemd drop-ins.
        pid = service.get("MainPID", "0")
        if pid.isdigit() and int(pid) > 0:
            try:
                with (Path("/proc") / pid / "environ").open("rb") as stream:
                    raw = stream.read(self.maximum + 1)
                if len(raw) <= self.maximum:
                    for entry in raw.decode("utf-8", errors="replace").split("\0"):
                        key, separator, value = entry.partition("=")
                        if separator and key in allowed:
                            values[key] = value
            except OSError:
                pass
        return values

    @staticmethod
    def container_environment(container):
        return dict(
            item.split("=", 1)
            for item in container.get("Config", {}).get("Env", [])
            if "=" in item and item.split("=", 1)[0] in {"XUI_DB_FOLDER", "XUI_DB_TYPE"}
        )

    @staticmethod
    def describe_container(container):
        network = container.get("NetworkSettings", {})
        ports = []
        for port, bindings in (network.get("Ports") or {}).items():
            for binding in bindings or []:
                ports.append(f"{binding.get('HostIp', '')}:{binding.get('HostPort', '')}->{port}")
        return {
            "container": container.get("Name", "").lstrip("/"),
            "image": container.get("Config", {}).get("Image", ""),
            "active": bool(container.get("State", {}).get("Running")),
            "network_mode": container.get("HostConfig", {}).get("NetworkMode", ""),
            "networks": sorted((network.get("Networks") or {}).keys()),
            "published_ports": sorted(ports),
        }

    @staticmethod
    def container_path(container, path):
        """Map a container path to its bind/volume or live process mount namespace."""
        if not path or not path.startswith("/") or ".." in PurePosixPath(path).parts:
            return None
        target = PurePosixPath(path)
        mounts = sorted(
            container.get("Mounts", []), key=lambda m: len(m.get("Destination", "")), reverse=True
        )
        for mount in mounts:
            destination = PurePosixPath(mount.get("Destination", "/"))
            if target == destination or destination in target.parents:
                source = mount.get("Source")
                if source and Path(source).is_absolute():
                    return Path(source).joinpath(*target.relative_to(destination).parts)
        pid = container.get("State", {}).get("Pid", 0)
        if isinstance(pid, int) and pid > 0:
            return Path(f"/proc/{pid}/root") / path.lstrip("/")
        return None

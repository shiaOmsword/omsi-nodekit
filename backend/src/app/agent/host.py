import os
import shutil
import socket
from pathlib import Path

from .context import AgentContext


class HostEnvironment:
    def __init__(self, context: AgentContext):
        self.context = context

    def port_open(self, port):
        try:
            with socket.create_connection(
                ("127.0.0.1", port), timeout=self.context.policy["socket_timeout"]
            ):
                return True
        except OSError:
            return False

    def require_free(self, port):
        with socket.socket() as sock:
            try:
                sock.bind(("0.0.0.0", port))
            except OSError as exc:
                raise RuntimeError(
                    f"Port {port} already occupied; existing services will not be stopped"
                ) from exc

    def environment(self):
        if os.geteuid() != 0:
            raise RuntimeError("Use root or ssh.sudo: true with non-interactive sudo")
        if not Path(self.context.policy["systemd_directory"]).exists():
            raise RuntimeError("Target must be a Linux VPS running systemd")
        for executable in ("docker", "ssh", "systemctl"):
            if not shutil.which(executable):
                raise RuntimeError(f"Missing prerequisite: {executable}")
        self.context.command(["docker", "info", "--format", "{{.ServerVersion}}"])
        self.context.command(["docker", "compose", "version"])
        self.context.emit("Docker daemon, Compose, OpenSSH and systemd available")

import os
import shutil
import socket
import sys
from pathlib import Path

from framework.messages import MessageKey
from framework.messages import text as message_text

from .context import AgentContext


class HostEnvironment:
    def __init__(self, context: AgentContext):
        self.context = context

    def port_open(self, port, address="127.0.0.1"):
        try:
            with socket.create_connection(
                (address, port), timeout=self.context.policy["socket_timeout"]
            ):
                return True
        except OSError:
            return False

    def require_free(self, port):
        with socket.socket() as sock:
            try:
                sock.bind(("0.0.0.0", port))
            except OSError as exc:
                raise RuntimeError(message_text(MessageKey.PORT_OCCUPIED, port=port)) from exc

    def require_endpoint(self, port, address):
        # The chosen listeners are IPv4; a dual-stack IPv6 wildcard also blocks this bind.
        for kind in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
            with socket.socket(socket.AF_INET, kind) as sock:
                try:
                    sock.bind((address, port))
                except OSError as exc:
                    raise RuntimeError(message_text(MessageKey.PORT_OCCUPIED, port=port)) from exc

    def environment(self):
        if sys.platform != "linux":
            raise RuntimeError(message_text(MessageKey.REMOTE_LINUX_REQUIRED))
        if os.geteuid() != 0:
            raise RuntimeError(message_text(MessageKey.ROOT_REQUIRED))
        if self.context.payload["action"] not in {"fresh", "restore"}:
            return
        if not Path(self.context.policy["systemd_directory"]).exists():
            raise RuntimeError(message_text(MessageKey.SYSTEMD_REQUIRED))
        if self.context.node.get("deployment"):
            if not shutil.which("systemctl"):
                raise RuntimeError(message_text(MessageKey.SYSTEMD_REQUIRED))
            return
        for executable in ("docker", "ssh", "systemctl"):
            if not shutil.which(executable):
                raise RuntimeError(message_text(MessageKey.PREREQUISITE_MISSING, name=executable))
        self.context.command(["docker", "info", "--format", "{{.ServerVersion}}"])
        self.context.command(["docker", "compose", "version"])
        self.context.emit(message_text(MessageKey.ENVIRONMENT_AVAILABLE))

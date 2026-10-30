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
        for executable in ("docker", "ssh", "systemctl"):
            if not shutil.which(executable):
                raise RuntimeError(message_text(MessageKey.PREREQUISITE_MISSING, name=executable))
        self.context.command(["docker", "info", "--format", "{{.ServerVersion}}"])
        self.context.command(["docker", "compose", "version"])
        self.context.emit(message_text(MessageKey.ENVIRONMENT_AVAILABLE))

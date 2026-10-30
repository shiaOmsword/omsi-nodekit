from dataclasses import dataclass
from pathlib import Path

from framework.messages import MessageKey
from framework.messages import text as message_text

from .execute import CommandRunner, ProcessError


@dataclass(frozen=True)
class SSHConnection:
    host: str
    user: str
    port: int
    identity_file: str
    known_hosts_file: str
    sudo: bool = False


@dataclass(frozen=True)
class SSHOptions:
    binary: str
    connect_timeout: int
    alive_interval: int
    alive_count: int
    python_command: str
    sudo_python_command: str


class SSHClient:
    def __init__(self, runner: CommandRunner, options: SSHOptions):
        self.runner = runner
        self.options = options

    def command(self, connection: SSHConnection) -> list[str]:
        identity = Path(connection.identity_file).expanduser().resolve()
        hosts = Path(connection.known_hosts_file).expanduser().resolve()
        for path in (identity, hosts):
            if not path.is_file():
                raise ProcessError(message_text(MessageKey.SSH_FILE_MISSING, path=path))
        # OpenSSH parses -o values itself; quoting also supports spaces in Windows paths.
        known_hosts = str(hosts).replace("\\", "/").replace('"', '\\"')
        return [
            self.options.binary,
            "-T",
            "-p",
            str(connection.port),
            "-i",
            str(identity),
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            f'UserKnownHostsFile="{known_hosts}"',
            "-o",
            f"ConnectTimeout={self.options.connect_timeout}",
            "-o",
            f"ServerAliveInterval={self.options.alive_interval}",
            "-o",
            f"ServerAliveCountMax={self.options.alive_count}",
            f"{connection.user}@{connection.host}",
            self.options.sudo_python_command if connection.sudo else self.options.python_command,
        ]

    def execute(self, connection: SSHConnection, script: str, *, timeout: float):
        return self.runner.stream(self.command(connection), script, timeout=timeout)

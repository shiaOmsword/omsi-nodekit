from dataclasses import dataclass, field
from pathlib import Path

from framework.messages import MessageKey
from framework.messages import text as message_text

from .execute import CommandRunner, ProcessError
from .sudo import SudoInput


@dataclass(frozen=True)
class SSHConnection:
    host: str
    user: str
    port: int
    identity_file: str
    known_hosts_file: str
    sudo: bool = False
    sudo_password: str | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class SSHOptions:
    binary: str
    connect_timeout: int
    alive_interval: int
    alive_count: int
    python_command: str
    sudo_python_command: str
    sudo_password_command: tuple[str, ...] = SudoInput.DEFAULT_COMMAND


class SSHClient:
    def __init__(self, runner: CommandRunner, options: SSHOptions):
        self.runner = runner
        self.options = options

    def command(self, connection: SSHConnection, *, protocol: SudoInput | None = None) -> list[str]:
        identity = Path(connection.identity_file).expanduser().resolve()
        hosts = Path(connection.known_hosts_file).expanduser().resolve()
        for path in (identity, hosts):
            if not path.is_file():
                raise ProcessError(message_text(MessageKey.SSH_FILE_MISSING, path=path))
        # OpenSSH parses -o values itself; quoting also supports spaces in Windows paths.
        known_hosts = str(hosts).replace("\\", "/").replace('"', '\\"')
        remote = self.options.python_command
        if connection.sudo:
            remote = (
                (protocol or SudoInput(connection.sudo_password)).command(
                    self.options.sudo_password_command
                )
                if connection.sudo_password is not None
                else self.options.sudo_python_command
            )
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
            remote,
        ]

    def execute(self, connection: SSHConnection, script: str, *, timeout: float):
        if connection.sudo_password is None:
            yield from self.runner.stream(self.command(connection), script, timeout=timeout)
            return
        if not connection.sudo:
            raise ProcessError(message_text(MessageKey.SUDO_PASSWORD_REQUIRES_ENABLED))
        protocol = SudoInput(connection.sudo_password)
        authenticated = False
        try:
            for line in self.runner.stream(
                self.command(connection, protocol=protocol),
                protocol.content(script),
                timeout=timeout,
            ):
                if not authenticated and protocol.authenticated(line):
                    authenticated = True
                    continue
                # Only authentication output is redacted: altering structured agent output
                # could corrupt a base64 database when a short password matches its bytes.
                yield line if authenticated else protocol.redact(line)
        except ProcessError as exc:
            if not authenticated:
                raise ProcessError(message_text(MessageKey.SUDO_START_FAILED)) from exc
            raise
        if not authenticated:
            raise ProcessError(message_text(MessageKey.SUDO_START_FAILED))

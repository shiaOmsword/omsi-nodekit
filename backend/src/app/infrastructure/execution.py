import base64
import binascii
import io
import zipfile
from pathlib import Path

from app.config import Settings
from app.entities import ExecutionEvent, InstallationReport
from app.ports import ArtifactRenderer, NodeExecutor
from app.services.keys import SSHKeyService
from framework.entities import InfrastructureError, JsonCodec
from framework.messages import MessageKey
from framework.messages import text as message_text
from framework.network import ProcessError, SSHClient, SSHConnection

from .auth import SudoPasswordResolver


class RemoteAgentBuilder:
    """Bundle only standard-library modules; the VPS never needs Poetry or punq."""

    def __init__(self, renderer: ArtifactRenderer, settings: Settings, codec: JsonCodec):
        self.renderer = renderer
        self.settings = settings
        self.codec = codec

    def build(self, node, action, backup=None, options=None):
        root = Path(__file__).resolve().parents[2]
        files = [
            "app/defaults.py",
            "app/system_backup.py",
            "app/backup_clients.py",
            "app/backup_wireguard.py",
            "app/backup_external_links.py",
            "framework/database/__init__.py",
            "framework/database/sqlite.py",
            "framework/database/snapshots.py",
            "framework/network/__init__.py",
            "framework/network/execute.py",
            "framework/network/ssh.py",
        ]
        files += [path.relative_to(root).as_posix() for path in (root / "app/agent").glob("*.py")]
        files += [
            path.relative_to(root).as_posix() for path in (root / "framework/messages").glob("*.py")
        ]
        files.append("framework/network/keys.py")
        files.append("framework/network/sudo.py")
        files += [
            path.relative_to(root).as_posix() for path in (root / "framework/utils").glob("*.py")
        ]
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for name in ("app/__init__.py", "framework/__init__.py"):
                bundle.writestr(name, "")
            for name in files:
                bundle.writestr(name, (root / name).read_bytes())
        payload = {
            "node": node.export_config(),
            "action": str(action),
            "files": self.renderer.artifacts(node),
            "runtime": {
                "deployment": self.settings.deployment.model_dump(mode="json"),
                "limits": self.settings.limits.model_dump(mode="json"),
                "discovery": self.settings.discovery.model_dump(mode="json"),
            },
        }
        if backup is not None:
            payload["backup"] = base64.b64encode(backup).decode()
        if options:
            payload["options"] = options
        encoded = base64.b64encode(archive.getvalue()).decode()
        return f"""import base64, io, json, sys, tempfile, zipfile
if sys.version_info < (3, 11):
    print(json.dumps({{"message": {message_text(MessageKey.REMOTE_PYTHON_REQUIRED)!r}, "level": "error"}}), flush=True)
    raise SystemExit(1)
with tempfile.TemporaryDirectory(prefix="nodekit-agent-") as folder:
    zipfile.ZipFile(io.BytesIO(base64.b64decode({encoded!r}))).extractall(folder)
    sys.path.insert(0, folder)
    from app.agent.runtime import RemoteAgent
    agent = RemoteAgent(json.loads({self.codec.dumps(payload)!r}))
    try:
        agent.run()
    except Exception as exc:
        agent.context.emit(str(exc), "error")
        raise SystemExit(1)
"""


class SSHNodeExecutor(NodeExecutor):
    def __init__(
        self,
        ssh: SSHClient,
        builder: RemoteAgentBuilder,
        codec: JsonCodec,
        settings: Settings,
        keys: SSHKeyService,
        passwords: SudoPasswordResolver,
    ):
        self.ssh = ssh
        self.builder = builder
        self.codec = codec
        self.settings = settings
        self.keys = keys
        self.passwords = passwords

    def execute(self, node, action, backup, options=None):
        connection_fields = node.ssh.model_dump(
            exclude={"key_id", "sudo_password", "sudo_password_env"}
        )
        connection_fields["sudo_password"] = self.passwords.resolve(node.ssh)
        if node.ssh.key_id:
            connection_fields["identity_file"] = str(self.keys.require(node.ssh.key_id))
        connection = SSHConnection(**connection_fields)
        try:
            script = self.builder.build(node, action, backup, options)
            yield ExecutionEvent(
                message=message_text(
                    MessageKey.SSH_CONNECTING,
                    user=node.ssh.user,
                    host=node.ssh.host,
                    port=node.ssh.port,
                )
            )
            for line in self.ssh.execute(
                connection, script, timeout=self.settings.ssh.operation_timeout
            ):
                try:
                    event = self.codec.loads(line)
                except ValueError:
                    yield ExecutionEvent(message=line.strip(), level="warning")
                    continue
                if not isinstance(event, dict):
                    raise InfrastructureError(message_text(MessageKey.REMOTE_EVENT_INVALID))
                if "report" in event:
                    if len(line.encode("utf-8")) > self.settings.discovery.metadata_bytes:
                        raise InfrastructureError(message_text(MessageKey.INSPECTION_TOO_LARGE))
                    yield ExecutionEvent(report=InstallationReport.model_validate(event["report"]))
                elif "backup" in event:
                    encoded = event["backup"]
                    if not isinstance(encoded, str) or len(encoded) > (
                        self.settings.limits.backup_bytes * 4 // 3 + 8
                    ):
                        raise InfrastructureError(message_text(MessageKey.REMOTE_BACKUP_TOO_LARGE))
                    yield ExecutionEvent(backup=base64.b64decode(encoded, validate=True))
                else:
                    yield ExecutionEvent(
                        message=str(event.get("message", "")), level=event.get("level", "info")
                    )
        except ProcessError as exc:
            raise InfrastructureError(str(exc)) from exc
        except (binascii.Error, ValueError) as exc:
            raise InfrastructureError(
                message_text(MessageKey.REMOTE_EVENT_PAYLOAD_INVALID)
            ) from exc

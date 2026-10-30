import base64
import json
import secrets
import tempfile
import time
from pathlib import Path

from app.defaults import NODE_DEFAULTS as D
from app.defaults import XUI_DATABASE_FILE
from framework.messages import MessageKey
from framework.messages import text as message_text

from .context import AgentContext
from .database import PanelDatabase
from .diagnostics import Diagnostics
from .host import HostEnvironment


class DeploymentService:
    def __init__(
        self,
        context: AgentContext,
        host: HostEnvironment,
        database: PanelDatabase,
        diagnostics: Diagnostics,
    ):
        self.context = context
        self.host = host
        self.database = database
        self.diagnostics = diagnostics

    def deploy(self, payload, base):
        import pwd

        node, action = payload["node"], payload["action"]
        if base.exists() and any(base.iterdir()):
            raise RuntimeError(message_text(MessageKey.TARGET_NOT_EMPTY))
        if self.context.status(["systemctl", "is-active", "--quiet", "x-ui"]) == 0:
            raise RuntimeError(message_text(MessageKey.NATIVE_PANEL_RUNNING))
        existing = self.context.command(
            [
                "docker",
                "ps",
                "-aq",
                "--filter",
                f"label=com.docker.compose.project={self.context.project()}",
            ]
        )
        if existing:
            raise RuntimeError(message_text(MessageKey.COMPOSE_PROJECT_EXISTS))
        ports = [node["panel"]["port"], node["panel"]["subscription_port"]]
        ports += [t["local_port"] for t in node["tunnels"]]
        if node["caddy"]["enabled"]:
            ports += [D.acme_http_port, node["caddy"]["https_port"]]
        for port in ports:
            self.host.require_free(port)
        for tunnel in node["tunnels"]:
            pwd.getpwnam(tunnel["user"])
            for key in ("identity_file", "known_hosts_file"):
                self.context.command(
                    ["runuser", "-u", tunnel["user"], "--", "test", "-r", tunnel[key]]
                )
        if action == "restore":
            raw = base64.b64decode(payload["backup"], validate=True)
            with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
                tmp.write(raw)
                tmp.flush()
                self.database.validate(tmp.name)
        self.context.emit(message_text(MessageKey.PREFLIGHT_COMPLETED))
        base.mkdir(parents=True, exist_ok=True, mode=0o700)
        base.chmod(0o700)
        for folder in ("db", "cert", "caddy-data", "caddy-config"):
            (base / folder).mkdir(mode=0o700)
        for name, content in payload["files"].items():
            (base / name).write_text(content)
            (base / name).chmod(0o600)
        compose = ["docker", "compose", "-f", str(base / "compose.yaml")]
        started_units = []
        try:
            self.context.command(compose + ["config", "--quiet"])
            self.context.emit(message_text(MessageKey.IMAGES_PULLING))
            self.context.command(compose + ["pull"], timeout=self.context.policy["pull_timeout"])
            db_path = base / "db" / XUI_DATABASE_FILE
            if action == "restore":
                db_path.write_bytes(raw)
                self.context.emit(message_text(MessageKey.DATABASE_RESTORED))
            else:
                password = secrets.token_urlsafe(self.context.policy["password_bytes"])
                self.context.command(
                    compose
                    + [
                        "run",
                        "--rm",
                        "--no-deps",
                        "--entrypoint",
                        "/app/x-ui",
                        "panel",
                        "setting",
                        "-username",
                        self.context.policy["panel_username"],
                        "-password",
                        password,
                        "-port",
                        str(node["panel"]["port"]),
                        "-listenIP",
                        "127.0.0.1",
                        "-webBasePath",
                        node["panel"]["base_path"],
                    ]
                )
                credentials = base / "credentials.json"
                credentials.write_text(
                    json.dumps(
                        {"username": self.context.policy["panel_username"], "password": password}
                    )
                )
                credentials.chmod(0o600)
                self.context.emit(message_text(MessageKey.CREDENTIALS_SAVED, path=credentials))
            self.database.validate(db_path)
            self.database.configure_listeners(db_path, node, action == "restore")
            db_path.chmod(0o600)
            # Copy only units belonging to this new node; refuse pre-existing names.
            for name, content in payload["files"].items():
                if name.endswith(".service"):
                    target = Path(self.context.policy["unit_directory"]) / name
                    if target.exists():
                        raise RuntimeError(message_text(MessageKey.UNIT_EXISTS, name=name))
                    target.write_text(content)
                    target.chmod(0o644)
                    started_units.append(name)
            if started_units:
                self.context.command(["systemctl", "daemon-reload"])
                self.context.command(["systemctl", "enable", "--now", *started_units])
            if node["caddy"]["enabled"]:
                self.context.command(
                    compose
                    + [
                        "run",
                        "--rm",
                        "--no-deps",
                        "caddy",
                        "caddy",
                        "validate",
                        "--config",
                        "/etc/caddy/Caddyfile",
                    ]
                )
            self.context.command(
                compose + ["up", "-d"], timeout=self.context.policy["startup_timeout"]
            )
            self.context.emit(message_text(MessageKey.SERVICES_STARTING))
            for _ in range(self.context.policy["readiness_attempts"]):
                if self.host.port_open(node["panel"]["port"]):
                    break
                time.sleep(self.context.policy["readiness_interval"])
            self.diagnostics.check(node, base)
            (base / "manifest.json").write_text(
                json.dumps({"node": node, "action": action}, indent=2)
            )
            self.context.emit(message_text(MessageKey.DEPLOYMENT_COMPLETED))
        except Exception:
            self.context.emit(
                message_text(MessageKey.DEPLOYMENT_FAILED),
                "error",
            )
            cleanup = [compose + ["stop"]]
            if started_units:
                cleanup.append(["systemctl", "disable", "--now", *started_units])
            for command in cleanup:
                try:
                    self.context.command(command)
                except Exception:
                    self.context.emit(message_text(MessageKey.CLEANUP_FAILED), "warning")
            raise

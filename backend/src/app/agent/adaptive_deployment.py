"""Fresh/restore for explicit native/Docker targets, optionally reusing shared Caddy."""

import base64
import json
import secrets
import shutil
import tempfile
import time
from pathlib import Path

from app.defaults import XUI_DATABASE_FILE
from framework.messages import MessageKey
from framework.messages import text as message_text

from .caddy_reuse import ExistingCaddy
from .native_release import NativeRelease, architecture
from .node_network import NodeNetwork
from .panel_api import InboundProvisioner, PanelAPI
from .subscriptions import preflight_caddy_network, verify_caddy_upstream


class AdaptiveDeployment:
    def __init__(self, context, host, database, diagnostics, inspector):
        self.context, self.host = context, host
        self.database, self.diagnostics, self.inspector = database, diagnostics, inspector

    def _docker(self):
        target = self.context.node["deployment"]
        needs = target["panel_runtime"] == "docker" or target["caddy_mode"] == "docker"
        if not needs:
            return
        if not shutil.which("docker"):
            if not target["install_docker"] or not shutil.which("apt-get"):
                raise RuntimeError(message_text(MessageKey.DEPLOYMENT_DOCKER_UNAVAILABLE))
            os_release = Path("/etc/os-release").read_text()
            if not any(
                line in {"ID=ubuntu", "ID=debian", 'ID="ubuntu"', 'ID="debian"'}
                for line in os_release.splitlines()
            ):
                raise RuntimeError(message_text(MessageKey.DEPLOYMENT_DOCKER_UNAVAILABLE))
            self.context.command(["apt-get", "update"], timeout=self.context.policy["pull_timeout"])
            self.context.command(["apt-cache", "show", "docker-compose-v2"])
            self.context.command(
                [
                    "env",
                    "DEBIAN_FRONTEND=noninteractive",
                    "apt-get",
                    "install",
                    "-y",
                    "docker.io",
                    "docker-compose-v2",
                ],
                timeout=self.context.policy["pull_timeout"],
            )
            self.context.command(["systemctl", "enable", "--now", "docker"])
        self.context.command(["docker", "info", "--format", "{{.ServerVersion}}"])
        self.context.command(["docker", "compose", "version"])

    def deploy(self, base):
        context = self.context
        node, target = context.node, context.node["deployment"]
        action = context.payload["action"]
        report = self.inspector.report
        if base.exists() and (base.is_symlink() or any(base.iterdir())):
            raise RuntimeError(message_text(MessageKey.TARGET_NOT_EMPTY))
        if report["panels"]:
            raise RuntimeError(message_text(MessageKey.DEPLOYMENT_EXISTS))
        needs_systemd = (
            target["panel_runtime"] == "native" or node["tunnels"] or target["install_docker"]
        )
        if report["warnings"] or (needs_systemd and not report["capabilities"].get("systemctl")):
            raise RuntimeError(message_text(MessageKey.DEPLOYMENT_DISCOVERY_INCOMPLETE))
        if target["panel_runtime"] == "native":
            architecture()
        if target["caddy_mode"] == "docker" and report["caddy"]:
            raise RuntimeError(message_text(MessageKey.CADDY_EXISTING_GUARD))
        caddy = (
            ExistingCaddy(context, self.inspector) if target["caddy_mode"] == "existing" else None
        )
        network = NodeNetwork(context, self.inspector, base)
        network.prepare()
        if caddy:
            caddy.preflight(allow_unpublished=bool(network.ports.missing))
        for port, bind in [
            (node["panel"]["port"], "127.0.0.1"),
            (node["panel"]["subscription_port"], target["subscription_bind"]),
        ]:
            self.host.require_endpoint(port, bind)
        for inbound in target["inbounds"] if action == "fresh" else []:
            self.host.require_endpoint(inbound["port"], inbound["listen"])
        if target["caddy_mode"] == "docker":
            for port in (80, node["caddy"]["https_port"]):
                self.host.require_endpoint(port, "0.0.0.0")
        for tunnel in node["tunnels"]:
            self.host.require_endpoint(tunnel["local_port"], "127.0.0.1")
            for key in ("identity_file", "known_hosts_file"):
                context.command(["runuser", "-u", tunnel["user"], "--", "test", "-r", tunnel[key]])
        for name in context.payload["files"]:
            if (
                name.endswith(".service")
                and (Path(context.policy["unit_directory"]) / name).exists()
            ):
                raise RuntimeError(message_text(MessageKey.UNIT_EXISTS, name=name))
        raw = None
        if action == "restore":
            raw = base64.b64decode(context.payload["backup"], validate=True)
            with tempfile.TemporaryDirectory() as folder:
                snapshot = Path(folder) / XUI_DATABASE_FILE
                snapshot.write_bytes(raw)
                self.database.validate(snapshot)
        context.emit(message_text(MessageKey.PREFLIGHT_COMPLETED))
        # Package installation is opt-in, after all collision and restore checks.
        try:
            network.allow()
            if caddy:
                preflight_caddy_network(context, caddy.finding)
            self._docker()
        except Exception:
            network.rollback()
            raise
        units = []
        compose = ["docker", "compose", "-f", str(base / "compose.yaml")]
        has_compose = "compose.yaml" in context.payload["files"]
        provisioner = None
        try:
            base.mkdir(parents=True, exist_ok=True, mode=0o700)
            base.chmod(0o700)
            if network.publish():
                caddy = ExistingCaddy(context, network.inspector)
                caddy.preflight()
            for folder in ("db", "cert", "logs", "caddy-data", "caddy-config"):
                (base / folder).mkdir(mode=0o700)
            for name, content in context.payload["files"].items():
                (base / name).write_text(content)
                (base / name).chmod(0o600)
            if has_compose:
                context.command(compose + ["config", "--quiet"])
                context.command(compose + ["pull"], timeout=context.policy["pull_timeout"])
            native = NativeRelease(context)
            if target["panel_runtime"] == "native":
                native.install(base)
                cli = native.command(base)
            else:
                cli = compose + ["run", "--rm", "--no-deps", "--entrypoint", "/app/x-ui", "panel"]
            db_path = base / "db" / XUI_DATABASE_FILE
            if action == "restore":
                db_path.write_bytes(raw)
            else:
                password = secrets.token_urlsafe(context.policy["password_bytes"])
                context.command(
                    cli
                    + [
                        "setting",
                        "-username",
                        context.policy["panel_username"],
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
                    json.dumps({"username": context.policy["panel_username"], "password": password})
                )
                credentials.chmod(0o600)
                context.emit(message_text(MessageKey.CREDENTIALS_SAVED, path=credentials))
            self.database.validate(db_path)
            self.database.configure_listeners(db_path, node, action == "restore")
            db_path.chmod(0o600)
            # Recheck all endpoints immediately before starting owned services.
            self.host.require_endpoint(node["panel"]["port"], "127.0.0.1")
            self.host.require_endpoint(
                node["panel"]["subscription_port"], target["subscription_bind"]
            )
            for name, content in context.payload["files"].items():
                if name.endswith(".service"):
                    path = Path(context.policy["unit_directory"]) / name
                    with path.open("x") as output:
                        output.write(content)
                    path.chmod(0o644)
                    units.append(name)
            if units:
                context.command(["systemctl", "daemon-reload"])
                context.command(["systemctl", "enable", "--now", *units])
            if has_compose:
                if target["caddy_mode"] == "docker":
                    context.command(
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
                context.command(compose + ["up", "-d"], timeout=context.policy["startup_timeout"])
            for _ in range(context.policy["readiness_attempts"]):
                if self.host.port_open(node["panel"]["port"]) and self.host.port_open(
                    node["panel"]["subscription_port"], target["subscription_bind"]
                ):
                    break
                time.sleep(context.policy["readiness_interval"])
            self.diagnostics.check(node, base)
            if action == "fresh" and target["inbounds"]:
                api = PanelAPI.from_cli(context, cli, base)
                provisioner = InboundProvisioner(context, api, self.host)
                provisioner.apply(base)
            if caddy:
                verify_caddy_upstream(context, caddy.finding)
                caddy.apply(base, context.payload["files"]["Caddyfile.site"])
            (base / "manifest.json").write_text(
                json.dumps({"node": node, "action": action}, indent=2)
            )
            network.commit(self.host)
            context.emit(message_text(MessageKey.DEPLOYMENT_COMPLETED))
        except Exception:
            context.emit(message_text(MessageKey.DEPLOYMENT_FAILED), "error")
            cleanups = []
            if caddy:
                cleanups.append(caddy.rollback)
            if provisioner:
                cleanups.append(provisioner.rollback)
            if has_compose:
                cleanups.append(lambda: context.command(compose + ["stop"]))
            if units:
                cleanups.append(lambda: context.command(["systemctl", "disable", "--now", *units]))
            cleanups.append(network.rollback)
            for cleanup in cleanups:
                try:
                    cleanup()
                except Exception:
                    context.emit(message_text(MessageKey.DEPLOYMENT_ROLLBACK_FAILED), "error")
            # Keep owned files, DB and release for diagnosis; never remove shared resources.
            raise

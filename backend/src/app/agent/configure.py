"""Update only an owned panel and its exact saved site in a shared Caddyfile."""

import json
import re
import time

from framework.messages import MessageKey
from framework.messages import text as message_text

from .caddy_reuse import ExistingCaddy
from .native_release import NativeRelease
from .node_network import NodeNetwork
from .panel_api import InboundProvisioner, PanelAPI
from .subscriptions import public_base, verify_caddy_upstream
from .xhttp_manager import render_managed_site, load_routes


class ConfigureSubscriptions:
    def __init__(self, context, host, database, diagnostics, inspector):
        self.context, self.host, self.database = context, host, database
        self.diagnostics, self.inspector = diagnostics, inspector

    def apply(self, base):
        context, node = self.context, self.context.node
        target = node.get("deployment") or {}
        selected = self.inspector.selected
        try:
            if base.is_symlink():
                raise ValueError()
            previous = json.loads((base / "manifest.json").read_text())["node"]
            previous_site = (base / "Caddyfile.site").read_bytes()
            if (
                not selected
                or selected["installation"] != "managed"
                or not selected["active"]
                or node["panel"]["installation"] != "managed"
                or not previous_site
                or previous["id"] != node["id"]
                or target.get("caddy_mode") != "existing"
                or previous["deployment"]["caddy_mode"] != "existing"
                or target["panel_runtime"] != previous["deployment"]["panel_runtime"]
                or node["tunnels"] != previous["tunnels"]
                or any(
                    node["panel"][k] != previous["panel"][k]
                    for k in ("image", "port", "base_path", "subscription_path")
                )
            ):
                raise ValueError()
            source = self.inspector.database()
            if source.resolve() != (base / "db/x-ui.db").resolve():
                raise ValueError()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise RuntimeError(message_text(MessageKey.SUBSCRIPTION_CONFIGURE_GUARD)) from exc
        caddy = ExistingCaddy(context, self.inspector)
        network = NodeNetwork(context, self.inspector, base)
        network.prepare()
        caddy.preflight(
            previous_site,
            previous["caddy"]["domain"],
            allow_unpublished=bool(network.ports.missing),
        )
        compose = ["docker", "compose", "-f", str(base / "compose.yaml")]
        docker = target["panel_runtime"] == "docker"

        def control(action):
            context.command(
                compose + [action, "panel"]
                if docker
                else ["systemctl", action, context.unit("panel")]
            )

        cli = (
            compose + ["run", "--rm", "--no-deps", "--entrypoint", "/app/x-ui", "panel"]
            if docker
            else NativeRelease(context).command(base)
        )
        saved_files = {
            name: (base / name).read_bytes() if (base / name).exists() else None
            for name in (
                "Caddyfile.site",
                "manifest.json",
                "deployment.json",
                "tunnel-connections.json",
                "subscriptions.json",
                "inbound-identities.json",
            )
        }
        original_settings, provisioner = None, None
        try:
            network.allow()
            if network.publish():
                caddy = ExistingCaddy(context, network.inspector)
                caddy.preflight(previous_site, previous["caddy"]["domain"])
            control("stop")
            self.host.require_endpoint(
                node["panel"]["subscription_port"], target["subscription_bind"]
            )
            self.database.snapshot(source, base / f"before-configure-{time.time_ns()}.db")
            original_settings = self.database.configure_subscriptions(source, node)
            control("start")
            self._ready()
            self.diagnostics.check(node, base)
            verify_caddy_upstream(context, caddy.finding)
            if target["inbounds"]:
                token = base / "api-token"
                api = (
                    PanelAPI(context, token.read_text().strip())
                    if token.is_file()
                    else PanelAPI.from_cli(context, cli, base)
                )
                provisioner = InboundProvisioner(context, api, self.host)
                provisioner.apply(base, allow_existing=True)
            combined_site = render_managed_site(context.payload["files"]["Caddyfile.site"], load_routes(base))
            caddy.apply(base, combined_site)
            links_file = base / "subscriptions.json"
            if links_file.exists():
                links = json.loads(links_file.read_text())
                for link in links:
                    identifier = link["url"].rsplit("/", 1)[-1]
                    if re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", identifier):
                        link["url"] = public_base(node) + identifier
                links_file.write_text(json.dumps(links, indent=2))
                links_file.chmod(0o600)
            for name, value in {
                "Caddyfile.site": combined_site,
                "deployment.json": json.dumps(target, indent=2),
                "manifest.json": json.dumps({"node": node, "action": "configure"}, indent=2),
            }.items():
                (base / name).write_text(value)
                (base / name).chmod(0o600)
            network.commit(self.host)
            context.emit(message_text(MessageKey.SUBSCRIPTION_CONFIGURED))
        except Exception:
            cleanups = [caddy.rollback]
            if provisioner:
                cleanups.append(provisioner.rollback)
            if original_settings is not None:

                def restore():
                    control("stop")
                    self.database.restore_settings(source, original_settings)

                cleanups.append(restore)
            cleanups.append(lambda: control("start"))
            cleanups.append(network.rollback)
            for cleanup in cleanups:
                try:
                    cleanup()
                except Exception:
                    context.emit(message_text(MessageKey.DEPLOYMENT_ROLLBACK_FAILED), "error")
            for name, content in saved_files.items():
                try:
                    if content is None:
                        (base / name).unlink(missing_ok=True)
                    else:
                        (base / name).write_bytes(content)
                except OSError:
                    context.emit(message_text(MessageKey.DEPLOYMENT_ROLLBACK_FAILED), "error")
            raise

    def _ready(self):
        for _ in range(self.context.policy["readiness_attempts"]):
            if self.host.port_open(self.context.node["panel"]["port"]) and self.host.port_open(
                self.context.node["panel"]["subscription_port"],
                self.context.node["deployment"]["subscription_bind"],
            ):
                return
            time.sleep(self.context.policy["readiness_interval"])
        raise RuntimeError(message_text(MessageKey.DEPLOYMENT_API_FAILED))

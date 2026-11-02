"""Update only an owned panel and its exact saved site in a shared Caddyfile."""

import json
import re
import time

from framework.messages import MessageKey
from framework.messages import text as message_text

from .attach_caddy import AttachmentCaddy
from .caddy_reuse import ExistingCaddy
from .native_release import NativeRelease
from .node_network import NodeNetwork
from .panel_api import InboundProvisioner, PanelAPI
from .subscriptions import public_base, verify_caddy_upstream
from .xhttp_manager import load_routes, render_managed_site


class ConfigureSubscriptions:
    def __init__(self, context, host, database, diagnostics, inspector):
        self.context, self.host, self.database = context, host, database
        self.diagnostics, self.inspector = diagnostics, inspector

    def apply(self, base):
        context, node = self.context, self.context.node
        target = node.get("deployment") or {}
        selected = self.inspector.selected
        attaching = context.payload["action"] == "attach_caddy"
        try:
            if base.is_symlink() or (base / "manifest.json").is_symlink():
                raise ValueError()
            manifest_bytes = (base / "manifest.json").read_bytes()
            previous = json.loads(manifest_bytes)["node"]
            old_mode = (previous.get("deployment") or {}).get("caddy_mode")
            site = base / "Caddyfile.site"
            if site.is_symlink():
                raise ValueError()
            if attaching:
                if old_mode not in {"none", "docker"} or site.exists() or load_routes(base):
                    raise ValueError()
                previous_site = None
                settings = selected.get("settings", {}) if selected else {}
                if (
                    int(settings.get("webPort", 0)) != node["panel"]["port"]
                    or settings.get("webBasePath") != node["panel"]["base_path"]
                    or settings.get("webCertFile")
                    or bool(selected.get("container")) != (target.get("panel_runtime") == "docker")
                    or (
                        target.get("panel_runtime") == "docker"
                        and (
                            not selected["id"].startswith("docker:")
                            or selected.get("image") != node["panel"]["image"]
                        )
                    )
                    or (
                        target.get("panel_runtime") == "native"
                        and selected.get("service") != context.unit("panel")
                    )
                ):
                    raise ValueError()
            else:
                if old_mode in {"none", "docker"}:
                    raise RuntimeError(message_text(MessageKey.CADDY_ATTACH_REQUIRED))
                previous_site = site.read_bytes()
            if (
                not selected
                or selected["installation"] != "managed"
                or not selected["active"]
                or node["panel"]["installation"] != "managed"
                or (not attaching and not previous_site)
                or previous["id"] != node["id"]
                or target.get("caddy_mode") != "existing"
                or (not attaching and old_mode != "existing")
                or not node["caddy"]["enabled"]
                or target["panel_runtime"] != previous["deployment"]["panel_runtime"]
                or node["tunnels"] != previous["tunnels"]
                or any(
                    node["panel"][k] != previous["panel"][k]
                    for k in ("image", "port", "base_path", "subscription_path")
                )
            ):
                raise ValueError()
            source = self.inspector.database()
            if source.resolve() != (base / "db/x-ui.db").resolve() or (
                attaching and (source.is_symlink() or (base / "db").is_symlink())
            ):
                raise ValueError()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            key = (
                MessageKey.CADDY_ATTACH_CONFLICT
                if attaching
                else MessageKey.SUBSCRIPTION_CONFIGURE_GUARD
            )
            raise RuntimeError(message_text(key)) from exc

        def caddy_for(inspector):
            return (
                AttachmentCaddy(context, inspector, base, previous, self.host)
                if attaching
                else ExistingCaddy(context, inspector)
            )

        caddy = caddy_for(self.inspector)
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
            if attaching and docker:
                # The inventory proved this exact container's project/service and DB.
                # Do not execute a potentially edited Compose project to control it.
                context.command(["docker", action, selected["id"].split(":", 1)[1]])
                return
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
        if any((base / name).is_symlink() for name in saved_files):
            raise RuntimeError(message_text(MessageKey.CADDY_ATTACH_CONFLICT))
        if saved_files["manifest.json"] != manifest_bytes:
            raise RuntimeError(message_text(MessageKey.DEPLOYMENT_CADDY_CHANGED))
        written_files = {}
        original_settings, provisioner = None, None
        try:
            network.allow()
            if network.publish():
                caddy = caddy_for(network.inspector)
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
            if target["inbounds"] and not attaching:
                token = base / "api-token"
                api = (
                    PanelAPI(context, token.read_text().strip())
                    if token.is_file()
                    else PanelAPI.from_cli(context, cli, base)
                )
                provisioner = InboundProvisioner(context, api, self.host)
                provisioner.apply(base, allow_existing=True)
            combined_site = render_managed_site(
                context.payload["files"]["Caddyfile.site"], load_routes(base)
            )
            caddy.apply(base, combined_site)
            links_file = base / "subscriptions.json"
            if links_file.exists():
                links = json.loads(links_file.read_text())
                for link in links:
                    identifier = link["url"].rsplit("/", 1)[-1]
                    if re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", identifier):
                        link["url"] = public_base(node) + identifier
                if links_file.read_bytes() != saved_files["subscriptions.json"]:
                    raise RuntimeError(message_text(MessageKey.DEPLOYMENT_CADDY_CHANGED))
                content = json.dumps(links, indent=2).encode()
                links_file.write_bytes(content)
                links_file.chmod(0o600)
                written_files["subscriptions.json"] = content
            for name, value in {
                "Caddyfile.site": combined_site,
                "deployment.json": json.dumps(target, indent=2),
                "manifest.json": json.dumps(
                    {"node": node, "action": context.payload["action"]}, indent=2
                ),
            }.items():
                path = base / name
                if (
                    path.is_symlink()
                    or (path.read_bytes() if path.exists() else None) != saved_files[name]
                ):
                    raise RuntimeError(message_text(MessageKey.DEPLOYMENT_CADDY_CHANGED))
                path.write_bytes(value.encode())
                (base / name).chmod(0o600)
                written_files[name] = value.encode()
            network.commit(self.host)
            context.emit(
                message_text(
                    MessageKey.CADDY_ATTACH_APPLIED
                    if attaching
                    else MessageKey.SUBSCRIPTION_CONFIGURED
                )
            )
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
                # The provisioner has its own rollback. Never overwrite a concurrent
                # operator edit to attachment metadata while handling a failure.
                if attaching and name not in written_files:
                    continue
                try:
                    if attaching and (
                        (base / name).is_symlink()
                        or (base / name).read_bytes() != written_files[name]
                    ):
                        context.emit(message_text(MessageKey.DEPLOYMENT_ROLLBACK_FAILED), "error")
                        continue
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

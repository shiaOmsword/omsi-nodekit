"""Attach shared Caddy or promote this node's pristine standalone Docker Caddy."""

import json
import time

from framework.messages import MessageKey
from framework.messages import text as message_text

from .caddy_config import standalone_config
from .caddy_reuse import ExistingCaddy
from .discovery import SystemInventory
from .firewall import caddy_matches


class AttachmentCaddy(ExistingCaddy):
    def __init__(self, context, inspector, base, previous, host):
        super().__init__(context, inspector)
        self.base, self.previous, self.host = base, previous, host
        self.owned_container = None
        self.restarted = False

    def preflight(self, previous_site=None, previous_domain=None, *, allow_unpublished=False):
        candidates = [
            c
            for c in self.inspector.report["caddy"]
            if caddy_matches(c, self.context.node["deployment"]["caddy_id"])
        ]
        if len(candidates) == 1 and candidates[0]["installation"] == "docker":
            finding = candidates[0]
            identifier = finding["id"].split(":", 1)[1]
            container = next(
                (c for c in self.inspector.inventory.containers() if c["Id"] == identifier), None
            )
            source = (
                SystemInventory.container_path(container, finding["config_path"])
                if container and finding.get("config_path")
                else None
            )
            if source and source.resolve() == (self.base / "Caddyfile").resolve():
                labels = container.get("Config", {}).get("Labels") or {}
                config = container.get("Config", {})
                command = (config.get("Entrypoint") or []) + (config.get("Cmd") or [])
                invocation = ["caddy", "run", "--config", "/etc/caddy/Caddyfile"]
                expected = standalone_config(self.previous).encode()
                if (
                    self.previous["deployment"]["caddy_mode"] != "docker"
                    or labels.get("com.docker.compose.project") != self.context.project()
                    or labels.get("com.docker.compose.service") != "caddy"
                    or container.get("HostConfig", {}).get("NetworkMode") != "host"
                    or container.get("Config", {}).get("Image") != self.previous["caddy"]["image"]
                    or finding["config_path"] != "/etc/caddy/Caddyfile"
                    or command not in [invocation, invocation + ["--adapter", "caddyfile"]]
                    or source.is_symlink()
                    or source.read_bytes() != expected
                ):
                    raise RuntimeError(message_text(MessageKey.CADDY_ATTACH_CONFLICT))
                # The generated standalone configuration disables the admin API.
                # Only this exact owned container may be restarted to enable it.
                self.host.require_endpoint(2019, "127.0.0.1")
                self.owned_container = identifier
                previous_site, previous_domain = expected, self.previous["caddy"]["domain"]
        super().preflight(previous_site, previous_domain, allow_unpublished=allow_unpublished)

    def _require_unchanged(self):
        if not self.owned_container:
            return super()._require_unchanged()
        expected = self.updated if self.restarted else self.original
        if self.source.is_symlink() or self.source.read_bytes() != expected:
            raise RuntimeError(message_text(MessageKey.DEPLOYMENT_CADDY_CHANGED))
        self._command(
            self.prefix + ["caddy", "validate", "--config", self.path, "--adapter", "caddyfile"]
        )
        if self.restarted:
            adapted = json.loads(
                self._command(
                    self.prefix
                    + ["caddy", "adapt", "--config", self.path, "--adapter", "caddyfile"]
                )
            )
            if adapted != self._live():
                raise RuntimeError(message_text(MessageKey.DEPLOYMENT_CADDY_UNSAFE))

    def apply(self, base, snippet):
        if not self.owned_container:
            return super().apply(base, snippet)
        self._require_unchanged()
        backup = base / f"Caddyfile.before-attach-{time.time_ns()}"
        backup.write_bytes(self.original)
        backup.chmod(0o600)
        if self.source.is_symlink() or self.source.read_bytes() != self.original:
            raise RuntimeError(message_text(MessageKey.DEPLOYMENT_CADDY_CHANGED))
        # Bind the admin endpoint explicitly to loopback on this host-network container.
        self.updated = ("{\n    admin 127.0.0.1:2019\n}\n\n" + snippet).encode()
        self.changed = True
        self.source.write_bytes(self.updated)
        self._command(
            self.prefix + ["caddy", "validate", "--config", self.path, "--adapter", "caddyfile"]
        )
        self.restarted = True
        self.context.command(["docker", "restart", self.owned_container])
        for _ in range(self.context.policy["readiness_attempts"]):
            try:
                self._require_unchanged()
                self.context.emit(message_text(MessageKey.DEPLOYMENT_CADDY_RELOADED))
                return
            except (OSError, ValueError, RuntimeError):
                time.sleep(self.context.policy["readiness_interval"])
        raise RuntimeError(message_text(MessageKey.DEPLOYMENT_CADDY_UNSAFE))

    def rollback(self):
        if not self.owned_container:
            return super().rollback()
        if not self.changed:
            return
        if self.source.is_symlink() or self.source.read_bytes() not in {
            self.original,
            self.updated,
        }:
            raise RuntimeError(message_text(MessageKey.DEPLOYMENT_CADDY_CHANGED))
        self.source.write_bytes(self.original)
        if self.restarted:
            self.context.command(["docker", "restart", self.owned_container])
        self.changed = False


def attachment_status(context):
    """Return only non-secret persisted state, never the manifest itself."""
    base = context.directory()
    try:
        manifest = base / "manifest.json"
        if base.is_symlink() or manifest.is_symlink():
            return "unknown"
        saved = json.loads(manifest.read_text(encoding="utf-8"))["node"]
        if saved["id"] != context.node["id"]:
            return "unknown"
        mode = (saved.get("deployment") or {}).get("caddy_mode")
        site = base / "Caddyfile.site"
        if mode == "existing" and site.is_file() and not site.is_symlink() and site.stat().st_size:
            return "ready"
        if mode in {"none", "docker"} and not site.exists() and not site.is_symlink():
            return "required"
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return "unknown"

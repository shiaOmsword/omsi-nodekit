"""Transactional addition of one site to an explicitly selected shared Caddy."""

import json
import urllib.request
from pathlib import Path

from framework.messages import MessageKey
from framework.messages import text as message_text

from .discovery import SystemInventory


class ExistingCaddy:
    def __init__(self, context, inspector):
        self.context = context
        self.inspector = inspector
        self.source = None
        self.original = None
        self.changed = False

    def _command(self, args):
        try:
            output = self.context.runner.run(
                args, timeout=self.context.policy["command_timeout"], sensitive=True
            )
            if len(output.encode()) > self.context.discovery["metadata_bytes"]:
                raise ValueError()
            return output
        except (RuntimeError, ValueError) as exc:
            raise RuntimeError(message_text(MessageKey.DEPLOYMENT_CADDY_UNSAFE)) from exc

    def _live(self):
        if self.prefix:
            return json.loads(
                self._command(self.prefix + ["wget", "-qO-", "http://127.0.0.1:2019/config/"])
            )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(
            "http://127.0.0.1:2019/config/", timeout=self.context.policy["http_timeout"]
        ) as response:
            data = response.read(self.context.discovery["metadata_bytes"] + 1)
        if len(data) > self.context.discovery["metadata_bytes"]:
            raise ValueError()
        return json.loads(data)

    def preflight(self):
        node = self.context.node
        target = node["deployment"]
        candidates = [c for c in self.inspector.report["caddy"] if c["id"] == target["caddy_id"]]
        if len(candidates) != 1:
            raise RuntimeError(message_text(MessageKey.DEPLOYMENT_CADDY_SELECTION))
        found = candidates[0]
        if (
            not found["active"]
            or found.get("config_source") != "file"
            or not found.get("config_path")
        ):
            raise RuntimeError(message_text(MessageKey.DEPLOYMENT_CADDY_UNSAFE))
        self.path = found["config_path"]
        self.prefix = []
        self.source = Path(self.path)
        expected_bind = "127.0.0.1"
        if found["installation"] == "docker":
            identifier = found["id"].split(":", 1)[1]
            containers = self.inspector.inventory.containers()
            container = next((c for c in containers if c["Id"] == identifier), None)
            if container is None:
                raise RuntimeError(message_text(MessageKey.DEPLOYMENT_CADDY_UNSAFE))
            self.source = SystemInventory.container_path(container, self.path)
            self.prefix = ["docker", "exec", identifier]
            if found.get("network_mode") != "host":
                expected_bind = found.get("host_gateway")
                port = node["caddy"]["https_port"]
                # Never silently alter somebody else's Docker port publications.
                if not any(p.endswith(f":{port}->{port}/tcp") for p in found["published_ports"]):
                    raise RuntimeError(message_text(MessageKey.DEPLOYMENT_CADDY_UNSAFE))
        if target["subscription_bind"] != expected_bind:
            raise RuntimeError(message_text(MessageKey.DEPLOYMENT_BIND_INVALID))
        if not self.source or str(self.source).startswith("/proc/") or not self.source.is_file():
            raise RuntimeError(message_text(MessageKey.DEPLOYMENT_CADDY_UNSAFE))
        if self.source.stat().st_size > self.context.discovery["metadata_bytes"]:
            raise RuntimeError(message_text(MessageKey.DEPLOYMENT_CADDY_UNSAFE))
        self.original = self.source.read_bytes()
        self._require_unchanged()
        for route in found["routes"]:
            if any(h == node["caddy"]["domain"] or h.startswith("*.") for h in route["hosts"]):
                raise RuntimeError(message_text(MessageKey.DEPLOYMENT_CADDY_COLLISION))

    def _require_unchanged(self):
        try:
            adapted = json.loads(
                self._command(
                    self.prefix
                    + ["caddy", "adapt", "--config", self.path, "--adapter", "caddyfile"]
                )
            )
            if self.source.read_bytes() != self.original or adapted != self._live():
                raise ValueError()
        except (OSError, ValueError, RuntimeError) as exc:
            raise RuntimeError(message_text(MessageKey.DEPLOYMENT_CADDY_UNSAFE)) from exc

    def apply(self, base, snippet):
        self._require_unchanged()
        backup = base / "Caddyfile.original"
        backup.write_bytes(self.original)
        backup.chmod(0o600)
        if self.source.read_bytes() != self.original:
            raise RuntimeError(message_text(MessageKey.DEPLOYMENT_CADDY_CHANGED))
        self.updated = self.original + b"\n\n" + snippet.encode()
        # Keep the inode: an existing Docker mount may bind this individual file.
        self.changed = True
        self.source.write_bytes(self.updated)
        self._command(
            self.prefix + ["caddy", "validate", "--config", self.path, "--adapter", "caddyfile"]
        )
        self._command(
            self.prefix + ["caddy", "reload", "--config", self.path, "--adapter", "caddyfile"]
        )
        adapted = json.loads(
            self._command(
                self.prefix + ["caddy", "adapt", "--config", self.path, "--adapter", "caddyfile"]
            )
        )
        if adapted != self._live():
            raise RuntimeError(message_text(MessageKey.DEPLOYMENT_CADDY_UNSAFE))
        self.context.emit(message_text(MessageKey.DEPLOYMENT_CADDY_RELOADED))

    def rollback(self):
        if not self.changed:
            return
        if self.source.read_bytes() not in {self.original, self.updated}:
            raise RuntimeError(message_text(MessageKey.DEPLOYMENT_CADDY_CHANGED))
        self.source.write_bytes(self.original)
        self._command(
            self.prefix + ["caddy", "reload", "--config", self.path, "--adapter", "caddyfile"]
        )
        self.changed = False

"""Publish missing ports without replacing any source Compose file or other service."""

import copy
import hashlib
import json
import re
import socket
import time
from pathlib import Path

from framework.messages import MessageKey
from framework.messages import text as message_text

from .firewall import caddy_matches


class CaddyPortsTransaction:
    def __init__(self, context, inspector):
        self.context, self.inspector = context, inspector
        self.changed = False
        self.up_attempted = False
        self.missing = []

    def _read(self, args):
        raw = self.context.runner.run(
            args, timeout=self.context.policy["command_timeout"], sensitive=True
        )
        if len(raw.encode()) > self.context.discovery["metadata_bytes"]:
            raise RuntimeError(message_text(MessageKey.NETWORK_COMPOSE_UNSAFE))
        return raw

    def prepare(self):
        node = self.context.node
        target = node.get("deployment") or {}
        if target.get("caddy_mode") != "existing":
            return
        proxies = [
            p for p in self.inspector.report["caddy"] if caddy_matches(p, target.get("caddy_id"))
        ]
        if len(proxies) != 1:
            return
        self.proxy = proxies[0]
        if self.proxy["installation"] != "docker" or self.proxy.get("network_mode") == "host":
            return
        for port in sorted({80, node["caddy"]["https_port"]}):
            if not any(
                p.endswith(f":{port}->{port}/tcp") for p in self.proxy.get("published_ports", [])
            ):
                self.missing.append(port)
        if not self.missing or not target.get("manage_caddy_ports", True):
            self.missing = []
            return
        try:
            self.name = self.proxy["container"]
            self.project, self.service = (
                self.proxy["compose_project"],
                self.proxy["compose_service"],
            )
            self.workdir = Path(self.proxy["compose_working_dir"])
            self.files = [Path(p) for p in self.proxy["compose_files"]]
            if (
                not self.workdir.is_absolute()
                or not self.workdir.is_dir()
                or not self.files
                or not all(
                    p.is_absolute() and p.is_file() and not p.is_symlink() for p in self.files
                )
                or not all(
                    re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", s or "")
                    for s in (self.name, self.project, self.service)
                )
            ):
                raise ValueError()
            containers = self.inspector.inventory.containers()
            actual = next(c for c in containers if c["Id"] == self.proxy["id"].split(":", 1)[1])
            labels = actual.get("Config", {}).get("Labels") or {}
            expected = labels.get("com.docker.compose.config-hash")
            self.expected_id, self.expected_hash = actual["Id"], expected
            self.applied_id = None
            self.prefix = [
                "docker",
                "compose",
                "--project-directory",
                str(self.workdir),
                "-p",
                self.project,
            ]
            self.old_args = self.prefix + [v for p in self.files for v in ("-f", str(p))]
            hashes = re.findall(
                r"\b[a-f0-9]{64}\b", self._read(self.old_args + ["config", "--hash", self.service])
            )
            if not expected or hashes != [expected]:
                raise RuntimeError(message_text(MessageKey.NETWORK_COMPOSE_DRIFT))
            self.old_config = json.loads(self._read(self.old_args + ["config", "--format", "json"]))
            old_service = self.old_config["services"][self.service]
            if old_service.get("image") != actual.get("Config", {}).get("Image"):
                raise ValueError()
            for port in self.missing:
                for mapping in old_service.get("ports", []):
                    if (
                        str(mapping.get("published")) == str(port)
                        and mapping.get("protocol", "tcp") == "tcp"
                    ):
                        raise RuntimeError(message_text(MessageKey.NETWORK_COMPOSE_DRIFT))
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                    listener.bind(("0.0.0.0", port))
            self.output = self.workdir / f"compose.nodekit-{node['id']}.ports.yaml"
            self.original = self.output.read_bytes() if self.output.exists() else None
            if self.output.is_symlink():
                raise ValueError()
            document = json.loads(self.original) if self.original else {}
            if document and document.get("x-nodekit-owner") != node["id"]:
                raise ValueError()
            if document and (
                set(document) != {"x-nodekit-owner", "services"}
                or set(document["services"]) != {self.service}
                or set(document["services"][self.service]) != {"ports"}
            ):
                raise ValueError()
            self.document = {
                "x-nodekit-owner": node["id"],
                "services": {
                    self.service: {
                        "ports": document.get("services", {}).get(self.service, {}).get("ports", [])
                        + [
                            {"target": p, "published": str(p), "protocol": "tcp"}
                            for p in self.missing
                        ]
                    }
                },
            }
            self.source_hashes = {
                p: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.files
                if p != self.output
            }
            self.new_args = (
                self.old_args
                if self.output in self.files
                else self.old_args + ["-f", str(self.output)]
            )
        except (OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
            raise RuntimeError(message_text(MessageKey.NETWORK_COMPOSE_UNSAFE)) from exc

    def apply(self):
        if not self.missing:
            return False
        current = json.loads(self._read(["docker", "inspect", self.name]))[0]
        if (
            current["Id"] != self.expected_id
            or (current.get("Config", {}).get("Labels") or {}).get("com.docker.compose.config-hash")
            != self.expected_hash
        ):
            raise RuntimeError(message_text(MessageKey.NETWORK_COMPOSE_DRIFT))
        if any(
            hashlib.sha256(p.read_bytes()).hexdigest() != digest
            for p, digest in self.source_hashes.items()
        ):
            raise RuntimeError(message_text(MessageKey.NETWORK_COMPOSE_DRIFT))
        if (
            self.output.is_symlink()
            or (self.output.read_bytes() if self.output.exists() else None) != self.original
        ):
            raise RuntimeError(message_text(MessageKey.NETWORK_COMPOSE_DRIFT))
        self.changed = True
        self.updated_bytes = json.dumps(self.document, indent=2).encode("utf-8")
        self.output.write_bytes(self.updated_bytes)
        self.output.chmod(0o600)
        try:
            merged = json.loads(self._read(self.new_args + ["config", "--format", "json"]))
            original, proposed = (
                copy.deepcopy(self.old_config["services"][self.service]),
                merged["services"][self.service],
            )
            original.pop("ports", None)
            proposed = {k: v for k, v in proposed.items() if k != "ports"}
            if original != proposed:
                raise RuntimeError(message_text(MessageKey.NETWORK_COMPOSE_DRIFT))
            self.up_attempted = True
            self.context.runner.run(
                self.new_args
                + ["up", "-d", "--no-deps", "--no-build", "--pull", "never", self.service],
                timeout=self.context.policy["startup_timeout"],
                sensitive=True,
            )
            self.applied_id = json.loads(self._read(["docker", "inspect", self.name]))[0]["Id"]
            for _ in range(self.context.policy["readiness_attempts"]):
                result = self.context.runner.completed(
                    ["docker", "exec", self.name, "wget", "-qO-", "http://127.0.0.1:2019/config/"],
                    timeout=self.context.policy["http_timeout"],
                )
                if result.returncode == 0:
                    break
                time.sleep(self.context.policy["readiness_interval"])
            else:
                raise RuntimeError(message_text(MessageKey.DEPLOYMENT_CADDY_UNSAFE))
            self.context.node["deployment"]["caddy_id"] = "docker:" + self.name
            self.context.emit(message_text(MessageKey.NETWORK_COMPOSE_APPLIED, path=self.output))
            return True
        except Exception:
            self.rollback()
            raise

    def rollback(self):
        if not self.changed:
            return
        if (
            self.applied_id
            and json.loads(self._read(["docker", "inspect", self.name]))[0]["Id"] != self.applied_id
        ):
            raise RuntimeError(message_text(MessageKey.NETWORK_COMPOSE_DRIFT))
        actual = self.output.read_bytes() if self.output.exists() else None
        if actual not in (self.original, self.updated_bytes):
            raise RuntimeError(message_text(MessageKey.NETWORK_COMPOSE_DRIFT))
        if self.original is None:
            self.output.unlink(missing_ok=True)
        else:
            self.output.write_bytes(self.original)
        if not self.up_attempted:
            self.changed = False
            return
        if any(
            hashlib.sha256(p.read_bytes()).hexdigest() != digest
            for p, digest in self.source_hashes.items()
        ):
            raise RuntimeError(message_text(MessageKey.NETWORK_COMPOSE_DRIFT))
        self.context.runner.run(
            self.old_args
            + ["up", "-d", "--no-deps", "--no-build", "--pull", "never", self.service],
            timeout=self.context.policy["startup_timeout"],
            sensitive=True,
        )
        self.changed = False

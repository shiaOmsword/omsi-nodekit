"""Install an SSH exit without exporting credentials or replacing unrelated routes."""

import copy
import json
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path

from framework.messages import MessageKey
from framework.messages import text as message_text

from .egress import curl_probe, runtime_paths
from .inbound_manager import managed_api
from .inbound_meta import public_inbound
from .tunnel_forward import TunnelForward


def routed_template(original, source_tag, tunnel, owned_tag, inbound_tag, previous=None):
    config = copy.deepcopy(original)
    sources = [o for o in config.get("outbounds", []) if o.get("tag") == source_tag]
    if len(sources) != 1 or source_tag == owned_tag:
        raise ValueError()
    source = sources[0]
    stream = source.get("streamSettings") or {}
    endpoints = (source.get("settings") or {}).get("vnext", [])
    if (
        source.get("protocol") != "vless"
        or len(endpoints) != 1
        or not endpoints[0].get("users")
        or not endpoints[0].get("address")
        or stream.get("network", "tcp") not in {"tcp", "raw"}
        or stream.get("security") != "reality"
        or source.get("proxySettings")
        or (stream.get("sockopt") or {}).get("dialerProxy")
        or source.get("sendThrough")
    ):
        raise ValueError()
    outbound = copy.deepcopy(source)
    outbound["tag"] = owned_tag
    outbound["settings"]["vnext"][0].update(address="127.0.0.1", port=tunnel["local_port"])
    existing = [o for o in config["outbounds"] if o.get("tag") == owned_tag]
    if existing and (not previous or existing != [previous["outbound"]]):
        raise ValueError()
    if previous and not existing:
        raise ValueError()
    if existing:
        config["outbounds"] = [
            outbound if o.get("tag") == owned_tag else o for o in config["outbounds"]
        ]
    else:
        config["outbounds"].append(outbound)
    rules = config.setdefault("routing", {}).setdefault("rules", [])
    if previous:
        if previous["rule"].get("inboundTag") != [inbound_tag] or previous["rule"] not in rules:
            raise ValueError()
        if rules.count(previous["rule"]) != 1:
            raise ValueError()
        index = rules.index(previous["rule"])
        if any(r.get("outboundTag") == owned_tag for r in rules[:index] + rules[index + 1 :]):
            raise ValueError()
        return config, outbound, previous["rule"]
    if any(r.get("outboundTag") == owned_tag for r in rules):
        raise ValueError()
    rule = {"type": "field", "inboundTag": [inbound_tag], "outboundTag": owned_tag}
    protected = {o.get("tag") for o in config["outbounds"] if o.get("protocol") == "blackhole"}
    api_tag = (config.get("api") or {}).get("tag")
    if api_tag:
        protected.add(api_tag)
    index = 0
    while index < len(rules) and rules[index].get("outboundTag") in protected:
        index += 1
    rules.insert(index, rule)
    return config, outbound, rule


def private_write(path, data):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class TunnelManager:
    def __init__(self, context, host, database, inspector):
        self.context, self.host, self.database, self.inspector = context, host, database, inspector

    @staticmethod
    def template(api):
        # 3.11.0 encodes obj as JSON containing a dictionary xraySetting.
        # Other panel versions use an object containing a JSON string.
        value = api.request("xray/", {})
        if isinstance(value, str):
            value = json.loads(value)
        value = value["xraySetting"]
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, dict) or not isinstance(value.get("outbounds"), list):
            raise ValueError()
        return value

    def stage(self, value):
        self.context.emit(message_text(MessageKey.TUNNEL_STAGE, stage=value))
        return value

    def wait(self, check):
        for _ in range(self.context.policy["readiness_attempts"]):
            if check():
                return
            time.sleep(self.context.policy["readiness_interval"])
        raise ValueError()

    def runtime_matches(self, outbound, rule):
        try:
            path, _ = runtime_paths(self.context, self.inspector)
            config = json.loads(path.read_text(encoding="utf-8"))
            return outbound in config["outbounds"] and rule in config["routing"]["rules"]
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return False

    def probe(self, outbound, url="https://example.com/"):
        """Require actual HTTPS return traffic, rather than an SSH local TCP accept."""
        _, binary = runtime_paths(self.context, self.inspector)
        if not binary or not binary.is_file():
            raise ValueError()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        config = {
            "log": {"loglevel": "error"},
            "inbounds": [
                {
                    "listen": "127.0.0.1",
                    "port": port,
                    "protocol": "socks",
                    "settings": {"auth": "noauth", "udp": False},
                }
            ],
            "outbounds": [outbound],
        }
        with tempfile.TemporaryDirectory(prefix="nodekit-tunnel-probe-") as folder:
            path = Path(folder) / "client.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            path.chmod(0o600)
            with (Path(folder) / "private.log").open("wb") as log:
                process = subprocess.Popen(
                    [str(binary), "run", "-config", str(path)],
                    cwd=folder,
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                )
                try:
                    self.wait(lambda: process.poll() is None and self.host.port_open(port))
                    result = curl_probe(self.context, url, socks_port=port)
                    if not result["ok"] or not result.get("bytes"):
                        raise ValueError()
                    return result
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)

    def apply(self, base):
        context = self.context
        request = context.payload["options"]["tunnel"]
        api = managed_api(context, self.inspector, base)
        stage = self.stage("configuration and ownership preflight")
        attempted, forward = False, None
        original = proposed = None
        originals, writes = {}, {}
        try:
            tunnels = [t for t in context.node["tunnels"] if t["name"] == request["name"]]
            if len(tunnels) != 1 or request["name"] == "panel":
                raise ValueError()
            tunnel = tunnels[0]
            inbound = public_inbound(api.request(f"inbounds/get/{request['id']}"))
            if (
                not inbound["enabled"]
                or not inbound["tag"]
                or inbound["fingerprint"] != request["expected_fingerprint"]
            ):
                raise ValueError()
            state_path = base / f"tunnel-{request['name']}.json"
            manifest_path = base / "manifest.json"
            for path in (state_path, manifest_path):
                if path.is_symlink():
                    raise ValueError()
                originals[path] = path.read_bytes() if path.exists() else None
            manifest = json.loads(originals[manifest_path])
            previous = json.loads(originals[state_path]) if originals[state_path] else None
            if previous and previous.get("inbound_id", request["id"]) != request["id"]:
                raise ValueError()
            if previous and previous.get("inbound_id") == request["id"]:
                # 3x-ui migrates the route tag when an inbound's port changes.
                previous["rule"]["inboundTag"] = [inbound["tag"]]
            tag = f"ssh-{context.node['id']}-{tunnel['name']}"
            original = self.template(api)
            proposed, outbound, rule = routed_template(
                original,
                request["outbound_tag"],
                tunnel,
                tag,
                inbound["tag"],
                previous,
            )
            forward = TunnelForward(context, self.host, tunnel)
            forward.preflight()
            stamp = time.time_ns()
            self.database.snapshot(self.inspector.database(), base / f"before-tunnel-{stamp}.db")
            recovery = base / f"before-tunnel-{stamp}.json"
            recovery.write_text(json.dumps(original), encoding="utf-8")
            recovery.chmod(0o600)
            stage = self.stage("SSH authentication and loopback forwarding")
            forward.start()
            self.wait(forward.ready)
            stage = self.stage("HTTPS through the exit VLESS inbound")
            self.probe(outbound)
            stage = self.stage("concurrent-change check and routing API update")
            if (
                self.template(api) != original
                or public_inbound(api.request(f"inbounds/get/{request['id']}"))["fingerprint"]
                != request["expected_fingerprint"]
            ):
                raise ValueError()
            attempted = True
            api.request("xray/update", {"xraySetting": json.dumps(proposed)}, form=True)
            if self.template(api) != proposed:
                raise ValueError()
            api.request("server/restartXrayService", {})
            stage = self.stage("runtime route and return traffic verification")
            self.wait(lambda: self.runtime_matches(outbound, rule))
            self.probe(outbound)
            applied = {t["name"]: t for t in manifest["node"]["tunnels"]}
            applied[tunnel["name"]] = tunnel
            names = {t["name"] for t in context.node["tunnels"]}
            manifest["node"]["tunnels"] = [
                applied[t["name"]] for t in context.node["tunnels"] if t["name"] in applied
            ] + [t for name, t in applied.items() if name not in names]
            records = {
                state_path: {"outbound": outbound, "rule": rule, "inbound_id": request["id"]},
                manifest_path: manifest,
            }
            for path, value in records.items():
                current = path.read_bytes() if path.exists() else None
                if path.is_symlink() or current != originals[path]:
                    raise ValueError()
                data = json.dumps(value).encode("utf-8")
                private_write(path, data)
                writes[path] = data
        except Exception as exc:
            safe_to_stop = True
            if attempted:
                try:
                    current = self.template(api)
                    if current == proposed:
                        api.request("xray/update", {"xraySetting": json.dumps(original)}, form=True)
                        api.request("server/restartXrayService", {})
                        if self.template(api) != original:
                            raise ValueError()
                    elif current != original:
                        raise ValueError()
                except Exception:
                    safe_to_stop = False
                    context.emit(message_text(MessageKey.DEPLOYMENT_ROLLBACK_FAILED), "error")
            for path, data in writes.items():
                try:
                    if path.is_symlink() or path.read_bytes() != data:
                        raise ValueError()
                    if originals[path] is None:
                        path.unlink()
                    else:
                        private_write(path, originals[path])
                except Exception:
                    context.emit(message_text(MessageKey.DEPLOYMENT_ROLLBACK_FAILED), "error")
            if forward and safe_to_stop:
                try:
                    forward.rollback()
                except Exception:
                    context.emit(message_text(MessageKey.DEPLOYMENT_ROLLBACK_FAILED), "error")
            raise RuntimeError(message_text(MessageKey.TUNNEL_APPLY_FAILED, stage=stage)) from exc
        context.emit(message_text(MessageKey.TUNNEL_APPLIED, name=tunnel["name"], tag=tag))

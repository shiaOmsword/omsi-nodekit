"""Local authenticated 3x-ui API. Never log response bodies or keys."""

import json
import re
import secrets
import time
import urllib.request
import uuid
from urllib.parse import urlencode

from framework.messages import MessageKey
from framework.messages import text as message_text

from .subscriptions import public_base


class NoAPIRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class PanelAPI:
    def __init__(self, context, token):
        self.context = context
        panel = context.node["panel"]
        self.base = f"http://127.0.0.1:{panel['port']}{panel['base_path']}panel/api/"
        self.token = token
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoAPIRedirect())

    def request(self, path, data=None, *, form=False):
        request = urllib.request.Request(
            self.base + path,
            data=(urlencode(data).encode() if form else json.dumps(data).encode())
            if data is not None
            else None,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/x-www-form-urlencoded" if form else "application/json",
            },
        )
        try:
            with self.opener.open(request, timeout=self.context.policy["http_timeout"]) as response:
                raw = response.read(self.context.discovery["metadata_bytes"] + 1)
            if len(raw) > self.context.discovery["metadata_bytes"]:
                raise ValueError()
            result = json.loads(raw)
            if result.get("success") is not True:
                raise ValueError()
            return result.get("obj")
        except (OSError, ValueError, AttributeError) as exc:
            raise RuntimeError(message_text(MessageKey.DEPLOYMENT_API_FAILED)) from exc

    @classmethod
    def from_cli(cls, context, command, base):
        result = context.runner.run(
            command + ["setting", "-getApiToken", "-tokenName", "nodekit", "-tokenScope", "admin"],
            timeout=context.policy["command_timeout"],
            sensitive=True,
        )
        match = re.search(r"^apiToken:\s*(\S+)\s*$", result, re.MULTILINE)
        if not match:
            raise RuntimeError(message_text(MessageKey.DEPLOYMENT_API_FAILED))
        token_file = base / "api-token"
        token_file.write_text(match[1])
        token_file.chmod(0o600)
        return cls(context, match[1])


class InboundProvisioner:
    def __init__(self, context, api, host):
        self.context = context
        self.api = api
        self.host = host
        self.created = []
        self.mapping_path = None
        self.mapping_original = None

    def apply(self, base, *, allow_existing=False):
        self.mapping_path = base / "inbound-identities.json"
        self.mapping_original = (
            self.mapping_path.read_bytes() if self.mapping_path.exists() else None
        )
        mapping = json.loads(self.mapping_original) if self.mapping_original else {}
        desired = self.context.node["deployment"]["inbounds"]
        existing = self.api.request("inbounds/list") or []
        connections, subscriptions, pending = [], [], []
        exported = base / "tunnel-connections.json"
        previous_connections = json.loads(exported.read_text()) if exported.exists() else []
        used_ports = {
            item["outbound"]["settings"]["vnext"][0]["port"] for item in previous_connections
        }
        # Check every conflict before adding any inbound.
        for inbound in desired:
            if allow_existing and inbound["name"] in mapping:
                continue
            remark = f"nodekit:{self.context.node['id']}:{inbound['name']}"
            matching = [item for item in existing if item.get("remark") == remark]
            if allow_existing and len(matching) == 1:
                item = matching[0]
                try:
                    stream = item["streamSettings"]
                    stream = json.loads(stream) if isinstance(stream, str) else stream
                    reality = stream["realitySettings"]
                    if (
                        item["port"] != inbound["port"]
                        or item["listen"] != inbound["listen"]
                        or item["protocol"] != "vless"
                        or stream["security"] != "reality"
                        or reality["serverNames"] != [inbound["server_name"]]
                        or reality["dest"] != f"{inbound['server_name']}:{inbound['target_port']}"
                    ):
                        raise ValueError()
                except (KeyError, TypeError, ValueError) as exc:
                    raise RuntimeError(
                        message_text(MessageKey.DEPLOYMENT_INBOUND_COLLISION)
                    ) from exc
                mapping[inbound["name"]] = {"id": item["id"], "deleted": False}
                continue
            for item in existing:
                if item.get("port") == inbound["port"] or item.get("remark") == remark:
                    # A fresh deployment never adopts or rotates an existing identity.
                    raise RuntimeError(message_text(MessageKey.DEPLOYMENT_INBOUND_COLLISION))
            pending.append(inbound)
        for inbound in pending:
            self.host.require_endpoint(inbound["port"], inbound["listen"])
            local_port = 15443
            while local_port in used_ports:
                local_port += 1
            used_ports.add(local_port)
            keys = self.api.request("server/getNewX25519Cert")
            if (
                not isinstance(keys, dict)
                or not keys.get("privateKey")
                or not keys.get("publicKey")
            ):
                raise RuntimeError(message_text(MessageKey.DEPLOYMENT_API_FAILED))
            client_id, short_id = str(uuid.uuid4()), secrets.token_hex(8)
            subscription_id = secrets.token_urlsafe(18)
            email = inbound.get("client_email") or f"nodekit-{inbound['name']}"
            settings = {
                "clients": [
                    {
                        "id": client_id,
                        "email": email,
                        "subId": subscription_id,
                        "flow": "xtls-rprx-vision",
                        "enable": True,
                        "limitIp": 0,
                        "totalGB": 0,
                        "expiryTime": 0,
                    }
                ],
                "decryption": "none",
                "fallbacks": [],
            }
            stream = {
                "network": "tcp",
                "security": "reality",
                "tcpSettings": {"header": {"type": "none"}},
                "realitySettings": {
                    "show": False,
                    "xver": 0,
                    "dest": f"{inbound['server_name']}:{inbound['target_port']}",
                    "serverNames": [inbound["server_name"]],
                    "privateKey": keys["privateKey"],
                    "shortIds": [short_id],
                    "settings": {
                        "publicKey": keys["publicKey"],
                        "fingerprint": "chrome",
                        "spiderX": "/",
                    },
                },
            }
            data = {
                "remark": f"nodekit:{self.context.node['id']}:{inbound['name']}",
                "enable": True,
                "listen": inbound["listen"],
                "port": inbound["port"],
                "protocol": "vless",
                "settings": json.dumps(settings),
                "streamSettings": json.dumps(stream),
                "sniffing": json.dumps(
                    {"enabled": True, "destOverride": ["http", "tls", "quic"], "routeOnly": True}
                ),
                "allocate": json.dumps({"strategy": "always", "refresh": 5, "concurrency": 3}),
            }
            result = self.api.request("inbounds/add", data)
            identifier = result.get("id") if isinstance(result, dict) else None
            if not isinstance(identifier, int) or identifier <= 0:
                raise RuntimeError(message_text(MessageKey.DEPLOYMENT_API_FAILED))
            self.created.append(identifier)
            mapping[inbound["name"]] = {"id": identifier, "deleted": False}
            saved = self.api.request(f"inbounds/get/{identifier}")
            if not isinstance(saved, dict) or any(
                saved.get(k) != data[k] for k in ("remark", "port", "protocol", "listen", "enable")
            ):
                raise RuntimeError(message_text(MessageKey.DEPLOYMENT_API_FAILED))
            try:
                stored_settings = saved["settings"]
                stored_stream = saved["streamSettings"]
                if isinstance(stored_settings, str):
                    stored_settings = json.loads(stored_settings)
                if isinstance(stored_stream, str):
                    stored_stream = json.loads(stored_stream)
                reality = stored_stream["realitySettings"]
                if (
                    stored_settings["clients"][0]["id"] != client_id
                    or stored_settings["clients"][0].get("subId") != subscription_id
                    or reality["privateKey"] != keys["privateKey"]
                    or reality["shortIds"] != [short_id]
                    or reality["serverNames"] != [inbound["server_name"]]
                ):
                    raise ValueError()
            except (KeyError, TypeError, ValueError, IndexError) as exc:
                raise RuntimeError(message_text(MessageKey.DEPLOYMENT_API_FAILED)) from exc
            connections.append(
                {
                    "name": inbound["name"],
                    "exit_listen": inbound["listen"],
                    "exit_port": inbound["port"],
                    "ssh_target": f"127.0.0.1:{inbound['port']}",
                    "outbound": {
                        "protocol": "vless",
                        "tag": f"to-{self.context.node['id']}-{inbound['name']}",
                        "settings": {
                            "vnext": [
                                {
                                    "address": "127.0.0.1",
                                    "port": local_port,
                                    "users": [
                                        {
                                            "id": client_id,
                                            "encryption": "none",
                                            "flow": "xtls-rprx-vision",
                                        }
                                    ],
                                }
                            ]
                        },
                        "streamSettings": {
                            "network": "tcp",
                            "security": "reality",
                            "realitySettings": {
                                "serverName": inbound["server_name"],
                                "fingerprint": "chrome",
                                "publicKey": keys["publicKey"],
                                "shortId": short_id,
                                "spiderX": "/",
                            },
                        },
                    },
                }
            )
            if self.context.node["caddy"]["enabled"]:
                subscriptions.append(
                    {
                        "name": inbound["name"],
                        "email": email,
                        "url": public_base(self.context.node) + subscription_id,
                    }
                )
        self.mapping_path.write_text(json.dumps(mapping, indent=2), encoding="utf-8")
        self.mapping_path.chmod(0o600)
        if not pending:
            return
        path = base / "tunnel-connections.json"
        for filename, records in (
            ("tunnel-connections.json", connections),
            ("subscriptions.json", subscriptions),
        ):
            output = base / filename
            previous = json.loads(output.read_text()) if output.exists() else []
            names = {row["name"] for row in records}
            output.write_text(
                json.dumps(
                    [row for row in previous if row["name"] not in names] + records, indent=2
                )
            )
            output.chmod(0o600)
        self.api.request("server/restartXrayService", {})
        for inbound in pending:
            for _ in range(self.context.policy["readiness_attempts"]):
                if self.host.port_open(inbound["port"]):
                    break
                time.sleep(self.context.policy["readiness_interval"])
            else:
                raise RuntimeError(message_text(MessageKey.DEPLOYMENT_API_FAILED))
            self.context.emit(
                message_text(
                    MessageKey.DEPLOYMENT_INBOUND_VERIFIED,
                    name=inbound["name"],
                    listen=inbound["listen"],
                    port=inbound["port"],
                )
            )
        self.context.emit(message_text(MessageKey.DEPLOYMENT_CONNECTIONS_SAVED, path=path))

    def rollback(self):
        for identifier in reversed(self.created):
            self.api.request(f"inbounds/del/{identifier}", {})
        if self.mapping_path:
            if self.mapping_original is None:
                self.mapping_path.unlink(missing_ok=True)
            else:
                self.mapping_path.write_bytes(self.mapping_original)

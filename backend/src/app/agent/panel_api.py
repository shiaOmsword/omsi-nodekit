"""Local authenticated 3x-ui API. Never log response bodies or keys."""

import json
import re
import secrets
import time
import urllib.request
import uuid

from framework.messages import MessageKey
from framework.messages import text as message_text


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

    def request(self, path, data=None):
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(data).encode() if data is not None else None,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
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

    def apply(self, base):
        desired = self.context.node["deployment"]["inbounds"]
        existing = self.api.request("inbounds/list") or []
        connections = []
        # Check every conflict before adding any inbound.
        for inbound in desired:
            remark = f"nodekit:{self.context.node['id']}:{inbound['name']}"
            for item in existing:
                if item.get("port") == inbound["port"] or item.get("remark") == remark:
                    # A fresh deployment never adopts or rotates an existing identity.
                    raise RuntimeError(message_text(MessageKey.DEPLOYMENT_INBOUND_COLLISION))
        for inbound in desired:
            self.host.require_endpoint(inbound["port"], inbound["listen"])
            keys = self.api.request("server/getNewX25519Cert")
            if (
                not isinstance(keys, dict)
                or not keys.get("privateKey")
                or not keys.get("publicKey")
            ):
                raise RuntimeError(message_text(MessageKey.DEPLOYMENT_API_FAILED))
            client_id, short_id = str(uuid.uuid4()), secrets.token_hex(8)
            settings = {
                "clients": [
                    {
                        "id": client_id,
                        "email": f"nodekit-{inbound['name']}",
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
                                    "port": 15443 + len(connections),
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
        path = base / "tunnel-connections.json"
        path.write_text(json.dumps(connections, indent=2))
        path.chmod(0o600)
        self.api.request("server/restartXrayService", {})
        for inbound in desired:
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

"""Temporary local VLESS client: tests actual server routing without editing it."""

import json
import re
import socket
import sqlite3
import subprocess
import tempfile
import time
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

from framework.messages import MessageKey
from framework.messages import text as message_text

from .egress import TARGETS, curl_probe, runtime_paths
from .inbound_meta import object_value, public_inbound


class TrafficProbe:
    def __init__(self, context, host, inspector):
        self.context, self.host, self.inspector = context, host, inspector

    def _configuration(self, request, socks_port):
        finding = self.inspector.selected
        if not finding or finding["installation"] != "managed" or not finding["active"]:
            raise RuntimeError(message_text(MessageKey.TRAFFIC_UNSUPPORTED))
        with closing(
            sqlite3.connect(self.inspector.database().resolve().as_uri() + "?mode=ro", uri=True)
        ) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only=ON")
            value = db.execute(
                "SELECT id,remark,enable,listen,port,protocol,settings,stream_settings,tag FROM inbounds WHERE id=?",
                (request["id"],),
            ).fetchone()
        if value is None:
            raise RuntimeError(message_text(MessageKey.INBOUND_STALE))
        value = dict(value)
        if public_inbound(value)["fingerprint"] != request["expected_fingerprint"]:
            raise RuntimeError(message_text(MessageKey.INBOUND_STALE))
        if (
            len(value["settings"].encode()) + len(value["stream_settings"].encode())
            > self.context.discovery["metadata_bytes"]
        ):
            raise RuntimeError(message_text(MessageKey.TRAFFIC_UNSUPPORTED))
        stream, settings = object_value(value["stream_settings"]), object_value(value["settings"])
        reality = stream.get("realitySettings") or {}
        try:
            if (
                not value["enable"]
                or value["protocol"] != "vless"
                or stream.get("security") != "reality"
                or stream.get("network") not in {"tcp", "raw"}
            ):
                raise ValueError()
            now = int(time.time() * 1000)
            client = next(
                c
                for c in settings["clients"]
                if c.get("enable", True)
                and not c.get("limitIp")
                and (c.get("expiryTime", 0) == 0 or c.get("expiryTime", 0) > now)
            )
            key = (reality.get("settings") or {}).get("publicKey") or reality.get("publicKey")
            sni = reality["serverNames"][0]
            short_id = reality["shortIds"][0]
            if (
                not re.fullmatch(r"[a-zA-Z0-9_-]{43}", key or "")
                or not re.fullmatch(r"[a-fA-F0-9]{0,16}", short_id)
                or not re.fullmatch(r"[a-zA-Z0-9.-]{1,253}", sni)
                or not re.fullmatch(r"[a-fA-F0-9-]{36}", client["id"])
            ):
                raise ValueError()
        except (ValueError, KeyError, TypeError, IndexError, StopIteration) as exc:
            raise RuntimeError(message_text(MessageKey.TRAFFIC_UNSUPPORTED)) from exc
        address = value["listen"]
        if address in {None, "", "0.0.0.0", "::"}:
            address = "127.0.0.1"
        return {
            "log": {"loglevel": "error"},
            "inbounds": [
                {
                    "tag": "nodekit-probe",
                    "listen": "127.0.0.1",
                    "port": socks_port,
                    "protocol": "socks",
                    "settings": {"auth": "noauth", "udp": False},
                }
            ],
            "outbounds": [
                {
                    "tag": "nodekit-probe-out",
                    "protocol": "vless",
                    "settings": {
                        "vnext": [
                            {
                                "address": address,
                                "port": value["port"],
                                "users": [
                                    {
                                        "id": client["id"],
                                        "encryption": "none",
                                        "flow": client.get("flow", ""),
                                    }
                                ],
                            }
                        ]
                    },
                    "streamSettings": {
                        "network": stream["network"],
                        "security": "reality",
                        "realitySettings": {
                            "serverName": sni,
                            "fingerprint": (reality.get("settings") or {}).get("fingerprint")
                            or "chrome",
                            "publicKey": key,
                            "shortId": short_id,
                            "spiderX": "/",
                        },
                    },
                }
            ],
            "routing": {
                "rules": [
                    {
                        "type": "field",
                        "inboundTag": ["nodekit-probe"],
                        "outboundTag": "nodekit-probe-out",
                    }
                ]
            },
        }

    def run(self):
        request = self.context.payload["options"]["traffic"]
        _, binary = runtime_paths(self.context, self.inspector)
        if not binary or not binary.is_file():
            raise RuntimeError(message_text(MessageKey.TRAFFIC_UNSUPPORTED))
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            socks_port = listener.getsockname()[1]
        config = self._configuration(request, socks_port)
        checks = self.inspector.report.setdefault("traffic_checks", [])
        with tempfile.TemporaryDirectory(prefix="nodekit-traffic-") as folder:
            path = Path(folder) / "client.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            path.chmod(0o600)
            process = None
            try:
                with (Path(folder) / "private-error.log").open("wb") as log:
                    process = subprocess.Popen(
                        [str(binary), "run", "-config", str(path)],
                        cwd=folder,
                        stdout=log,
                        stderr=log,
                        start_new_session=True,
                    )
                    for _ in range(self.context.policy["readiness_attempts"]):
                        if process.poll() is not None:
                            raise RuntimeError(message_text(MessageKey.TRAFFIC_UNSUPPORTED))
                        if self.host.port_open(socks_port):
                            break
                        time.sleep(self.context.policy["readiness_interval"])
                    else:
                        raise RuntimeError(message_text(MessageKey.TRAFFIC_UNSUPPORTED))
                    for url in TARGETS:
                        for name, port in (("direct", None), ("inbound", socks_port)):
                            self.context.emit(
                                message_text(
                                    MessageKey.NETWORK_CHECK,
                                    name=name,
                                    state="running",
                                    detail=urlsplit(url).hostname,
                                )
                            )
                            result = curl_probe(self.context, url, socks_port=port)
                            detail = (
                                urlsplit(url).hostname
                                + " · "
                                + (
                                    "через выбранный VLESS/REALITY inbound"
                                    if port
                                    else "напрямую с VPS"
                                )
                                + " · "
                                + result["reason"]
                            )
                            if result.get("seconds") is not None:
                                detail += f" · {result['seconds']:.2f} с · {result['bytes']} байт"
                            item = {
                                "name": name,
                                "state": "ok" if result["ok"] else "error",
                                "detail": detail,
                            }
                            checks.append(item)
                            self.context.emit(
                                message_text(MessageKey.NETWORK_CHECK, **item),
                                "info" if result["ok"] else "error",
                            )
                    checks.append(
                        {
                            "name": "scope",
                            "state": "warning",
                            "detail": "Проба идёт с VPS через настоящий inbound и его routing. Внешний участок клиент → VPS и MTU не проверены. Пробный трафик учитывается в статистике выбранного клиента.",
                        }
                    )
            finally:
                if process and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
        return [c["detail"] for c in checks if c["state"] == "error"]

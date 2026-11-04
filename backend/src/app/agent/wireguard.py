import base64
import copy
import ipaddress
import json
import secrets
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import quote

from app.backup_wireguard import client_identity, key_bytes, read_wireguard
from framework.messages import MessageKey
from framework.messages import text as message_text

from .firewall import FirewallTransaction, desired_rules, rule_spec
from .inbound_manager import configuration, managed_api
from .inbound_meta import object_value, public_inbound
from .subscriptions import public_base


def stable_records(records):
    return sorted(
        ({k: v for k, v in record.items() if k != "traffic"} for record in records),
        key=lambda record: record.get("email", ""),
    )


def pair(api):
    generated = api.request("server/getNewX25519Cert")
    return {
        name: base64.b64encode(key_bytes(generated[name])).decode()
        for name in ("privateKey", "publicKey")
    }


def new_client(api, email, address):
    return {
        **pair(api),
        "email": email,
        "id": str(uuid.uuid4()),
        "subId": secrets.token_urlsafe(18),
        "enable": True,
        "allowedIPs": [address],
        "keepAlive": 25,
        "totalGB": 0,
        "expiryTime": 0,
        "limitIp": 0,
    }


class WireGuardManager:
    def __init__(self, context, host, database, inspector):
        self.context, self.host, self.database, self.inspector = context, host, database, inspector

    def apply(self, base):
        context = self.context
        request = context.payload["options"]["wireguard"]
        api = managed_api(context, self.inspector, base)
        if (
            not context.node["caddy"]["enabled"]
            or self.inspector.selected["settings"].get("subURI") != public_base(context.node)
            or self.inspector.selected["settings"].get("subEnable") != "true"
        ):
            raise RuntimeError(message_text(MessageKey.WIREGUARD_SUBSCRIPTIONS_REQUIRED))
        records = api.request("clients/list") or []
        existing = api.request("inbounds/list") or []
        if any(
            i.get("port") == request["port"] or i.get("remark") == request["remark"]
            for i in existing
        ):
            raise RuntimeError(message_text(MessageKey.DEPLOYMENT_INBOUND_COLLISION))
        if self.host.udp_port_bound(request["port"]):
            raise RuntimeError(message_text(MessageKey.PORT_OCCUPIED, port=request["port"]))
        if request["operation"] == "restore":
            raw = base64.b64decode(context.payload["backup"], validate=True)
            if len(raw) > context.limits["backup_bytes"]:
                raise RuntimeError(message_text(MessageKey.WIREGUARD_BACKUP_INVALID))
            with tempfile.TemporaryDirectory(prefix="nodekit-wg-") as folder:
                path = Path(folder) / "x-ui.db"
                path.write_bytes(raw)
                self.database.validate(path)
                source = next(
                    (i for i in read_wireguard(path) if i["id"] == request["source_inbound_id"]),
                    None,
                )
            if not source:
                raise RuntimeError(message_text(MessageKey.WIREGUARD_BACKUP_INVALID))
            settings = copy.deepcopy(source["settings"])
            clients = copy.deepcopy(source["clients"])
            for index, client in enumerate(clients):
                if not client.get("email"):
                    client["email"] = f"wg-restored-{source['id']}-{index + 1}"
                if not client.get("subId"):
                    client["subId"] = secrets.token_urlsafe(18)
                if not client.get("id"):
                    client["id"] = str(uuid.uuid4())
            settings.update(clients=clients, peers=[])
        else:
            subnet = ipaddress.ip_network(request["subnet"])
            clients = [new_client(api, request["client_email"], f"{subnet.network_address + 2}/32")]
            settings = {
                "secretKey": pair(api)["privateKey"],
                "clients": clients,
                "peers": [],
                "subnetIp": str(subnet.network_address),
                "subnetCidr": subnet.prefixlen,
                "noKernelTun": True,
            }
        if request["operation"] == "restore":
            settings.setdefault("mtu", request["mtu"])
            settings.setdefault("dns", request["dns"])
        else:
            settings.update(mtu=request["mtu"], dns=request["dns"])
        for field in ("email", "subId", "publicKey"):
            values = [
                key_bytes(c[field])
                if field == "publicKey"
                else c[field].lower()
                if field == "email"
                else c[field]
                for c in clients
            ]
            if len(values) != len(set(values)):
                raise RuntimeError(message_text(MessageKey.WIREGUARD_BACKUP_INVALID))
        # Never let the panel merge restored identities with a different global account.
        for client in clients:
            if any(
                str(r.get("email", "")).lower() == str(client["email"]).lower()
                or r.get("subId") == client.get("subId")
                or (
                    bool(r.get("publicKey"))
                    and key_bytes(r["publicKey"]) == key_bytes(client["publicKey"])
                )
                or r.get("uuid") == client.get("id")
                for r in records
            ):
                raise RuntimeError(message_text(MessageKey.CLIENT_IMPORT_CONFLICT))
        self.database.snapshot(
            self.inspector.database(), base / f"before-wireguard-{time.time_ns()}.db"
        )
        firewall = FirewallTransaction(
            context, base, enabled=(context.node.get("deployment") or {}).get("manage_ufw", True)
        )
        identifier = None
        proposed = {
            "remark": request["remark"],
            "enable": True,
            "listen": "0.0.0.0",
            "port": request["port"],
            "protocol": "wireguard",
            "settings": settings,
            "streamSettings": {},
            "sniffing": {"enabled": False},
            "shareAddrStrategy": "custom",
            "shareAddr": request["domain"],
        }
        try:
            if api.request("inbounds/list") != existing or stable_records(
                api.request("clients/list") or []
            ) != stable_records(records):
                raise RuntimeError(message_text(MessageKey.INBOUND_STALE))
            firewall.ensure(
                desired_rules(
                    context, self.inspector.report, extra=[rule_spec(request["port"], "udp")]
                )
            )
            payload = {k: json.dumps(v) if isinstance(v, dict) else v for k, v in proposed.items()}
            result = api.request("inbounds/add", payload)
            identifier = result.get("id") if isinstance(result, dict) else None
            if not isinstance(identifier, int) or identifier <= 0:
                raise RuntimeError(message_text(MessageKey.DEPLOYMENT_API_FAILED))
            saved = api.request(f"inbounds/get/{identifier}")
            actual = object_value(saved.get("settings"))
            if (
                saved.get("protocol") != "wireguard"
                or saved.get("port") != request["port"]
                or saved.get("shareAddr") != request["domain"]
                or actual.get("secretKey") != settings["secretKey"]
                or [client_identity(c) for c in actual.get("clients", [])]
                != [client_identity(c) for c in clients]
            ):
                raise RuntimeError(message_text(MessageKey.INBOUND_IDENTITIES))
            api.request("server/restartXrayService", {})
            for _ in range(context.policy["readiness_attempts"]):
                if self.host.udp_port_bound(request["port"]):
                    break
                time.sleep(context.policy["readiness_interval"])
            else:
                raise RuntimeError(message_text(MessageKey.WIREGUARD_NOT_READY))
            firewall.commit()
        except Exception:
            try:
                if identifier is None:
                    candidates = [
                        i
                        for i in (api.request("inbounds/list") or [])
                        if i.get("id") not in {old["id"] for old in existing}
                        and i.get("remark") == request["remark"]
                        and object_value(i.get("settings")).get("secretKey")
                        == settings["secretKey"]
                    ]
                    if len(candidates) == 1:
                        identifier = candidates[0]["id"]
                if identifier:
                    saved = api.request(f"inbounds/get/{identifier}")
                    if (
                        saved.get("remark") == request["remark"]
                        and object_value(saved.get("settings")).get("secretKey")
                        == settings["secretKey"]
                        and [
                            client_identity(c)
                            for c in object_value(saved.get("settings")).get("clients", [])
                        ]
                        == [client_identity(c) for c in clients]
                    ):
                        api.request(f"inbounds/del/{identifier}", {})
                        for c in clients:
                            remaining = next(
                                (
                                    r
                                    for r in (api.request("clients/list") or [])
                                    if r.get("email") == c["email"]
                                ),
                                None,
                            )
                            if (
                                remaining
                                and not remaining.get("inboundIds")
                                and all(
                                    (remaining.get(k) or "") == (c.get(k) or "")
                                    for k in ("privateKey", "publicKey", "subId")
                                )
                            ):
                                api.request("clients/del/" + quote(c["email"], safe=""), {})
                        api.request("server/restartXrayService", {})
                    else:
                        raise ValueError()
            except Exception:
                context.emit(message_text(MessageKey.DEPLOYMENT_ROLLBACK_FAILED), "error")
            firewall.rollback()
            raise
        context.emit(message_text(MessageKey.WIREGUARD_APPLIED, port=request["port"]))

    def client(self, base, api, original, change):
        if public_inbound(original)["fingerprint"] != change["expected_fingerprint"]:
            raise RuntimeError(message_text(MessageKey.INBOUND_STALE))
        settings = object_value(original.get("settings"))
        before = settings.get("clients", [])
        records = api.request("clients/list") or []
        email = change["client_email"]
        current = [r for r in records if str(r.get("email", "")).lower() == email.lower()]
        if change["operation"] == "add_client":
            if current:
                raise RuntimeError(message_text(MessageKey.CLIENT_IMPORT_CONFLICT))
            subnet = ipaddress.ip_network(
                f"{settings.get('subnetIp') or '10.0.0.0'}/{settings.get('subnetCidr') or 24}"
            )
            used = [
                ipaddress.ip_network(v, strict=False)
                for i in (api.request("inbounds/list") or [])
                if i.get("protocol") in {"wireguard", "amneziawg"}
                for c in object_value(i.get("settings")).get("clients", [])
                for v in c.get("allowedIPs", [])
            ]
            address = next(
                (
                    ip
                    for ip in subnet.hosts()
                    if ip != subnet.network_address + 1
                    and not any(ip.version == n.version and ip in n for n in used)
                ),
                None,
            )
            if address is None:
                raise RuntimeError(message_text(MessageKey.WIREGUARD_BACKUP_INVALID))
            client = new_client(api, email, f"{address}/32")
            after = before + [client]
        else:
            if len(current) != 1 or current[0].get("inboundIds") != [original["id"]]:
                raise RuntimeError(message_text(MessageKey.CLIENT_IMPORT_CONFLICT))
            client = next((c for c in before if c.get("email") == email), None)
            if not client:
                raise RuntimeError(message_text(MessageKey.CLIENT_IMPORT_CONFLICT))
            after = [c for c in before if c.get("email") != email]
        self.database.snapshot(
            self.inspector.database(), base / f"before-wg-client-{time.time_ns()}.db"
        )
        if configuration(api.request(f"inbounds/get/{original['id']}")) != configuration(
            original
        ) or stable_records(api.request("clients/list") or []) != stable_records(records):
            raise RuntimeError(message_text(MessageKey.INBOUND_STALE))
        try:
            if change["operation"] == "add_client":
                api.request("clients/add", {"client": client, "inboundIds": [original["id"]]})
            else:
                api.request("clients/del/" + quote(email, safe=""), {})
            saved = api.request(f"inbounds/get/{original['id']}")
            if [
                client_identity(c) for c in object_value(saved.get("settings")).get("clients", [])
            ] != [client_identity(c) for c in after] or object_value(saved.get("settings")).get(
                "secretKey"
            ) != settings.get("secretKey"):
                raise RuntimeError(message_text(MessageKey.INBOUND_IDENTITIES))
        except Exception:
            if change["operation"] == "add_client":
                try:
                    now = api.request("clients/list") or []
                    owned = next((r for r in now if r.get("email") == email), None)
                    if (
                        owned
                        and owned.get("inboundIds") == [original["id"]]
                        and all(
                            owned.get(k) == client.get(k)
                            for k in ("privateKey", "publicKey", "subId")
                        )
                    ):
                        api.request("clients/del/" + quote(email, safe=""), {})
                except Exception:
                    self.context.emit(message_text(MessageKey.DEPLOYMENT_ROLLBACK_FAILED), "error")
            raise
        self.context.emit(message_text(MessageKey.INBOUND_UPDATED, id=original["id"]))

"""Read wg-easy v15 snapshots without changing or generating key identities.

Only public_source() may cross the HTTP boundary. The SQLite source remains
the private, lossless archive of settings belonging to the old application.
"""

import base64
import ipaddress
import json
import re
import shlex
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from app.backup_clients import EMAIL, MAX_CLIENTS, MAX_INBOUNDS
from app.backup_wireguard import key_bytes
from framework.messages import MessageKey
from framework.messages import text as message_text

TABLES = {"interfaces_table", "clients_table", "user_configs_table", "hooks_table"}
COLUMNS = {
    "interfaces_table": {
        "name",
        "device",
        "port",
        "private_key",
        "public_key",
        "ipv4_cidr",
        "ipv6_cidr",
        "mtu",
        "enabled",
    },
    "clients_table": {
        "id",
        "interface_id",
        "name",
        "ipv4_address",
        "ipv6_address",
        "private_key",
        "public_key",
        "pre_shared_key",
        "enabled",
        "expires_at",
        "persistent_keepalive",
        "mtu",
        "dns",
        "allowed_ips",
        "server_allowed_ips",
        "server_endpoint",
        "pre_up",
        "post_up",
        "pre_down",
        "post_down",
    },
    "user_configs_table": {
        "id",
        "default_mtu",
        "default_persistent_keepalive",
        "default_dns",
        "default_allowed_ips",
        "host",
        "port",
    },
    "hooks_table": {"id", "pre_up", "post_up", "pre_down", "post_down"},
}


def invalid():
    return ValueError(message_text(MessageKey.WIREGUARD_BACKUP_INVALID))


def integer(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise invalid()
    return value


def text(value, limit=1024):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
        raise invalid()
    return value


def array(value):
    result = json.loads(value) if isinstance(value, str) else value
    if not isinstance(result, list) or len(result) > 100:
        raise invalid()
    return [text(v) for v in result]


def key(value, *, optional=False):
    if optional and not value:
        return ""
    return base64.b64encode(key_bytes(value)).decode()


def expiry(value):
    if value is None:
        return 0
    parsed = datetime.fromisoformat(text(value))
    # SQLite/Drizzle timestamps without an offset are UTC, not the host timezone.
    parsed = parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    return integer(int(parsed.timestamp() * 1000), 1, 2**53 - 1)


def default_hooks(hooks):
    if hooks["pre_up"].strip() or hooks["pre_down"].strip():
        return False
    for field, action in (("post_up", "-A"), ("post_down", "-D")):
        for command in hooks[field].split(";"):
            if not command.strip():
                continue
            tokens = shlex.split(command)
            if not tokens:
                return False
            expected = [
                [
                    "-t",
                    "nat",
                    action,
                    "POSTROUTING",
                    "-s",
                    "{{ipv4Cidr}}",
                    "-o",
                    "{{device}}",
                    "-j",
                    "MASQUERADE",
                ],
                [
                    "-t",
                    "nat",
                    action,
                    "POSTROUTING",
                    "-s",
                    "{{ipv6Cidr}}",
                    "-o",
                    "{{device}}",
                    "-j",
                    "MASQUERADE",
                ],
                [action, "INPUT", "-p", "udp", "-m", "udp", "--dport", "{{port}}", "-j", "ACCEPT"],
                [action, "FORWARD", "-i", "{{interface}}", "-j", "ACCEPT"],
                [action, "FORWARD", "-o", "{{interface}}", "-j", "ACCEPT"],
            ]
            tokens = ["{{interface}}" if t == hooks["id"] else t for t in tokens]
            if tokens[0] not in {"iptables", "ip6tables"} or tokens[1:] not in expected:
                return False
    return True


def public_source(source):
    return {
        "source_format": "wg-easy-v15",
        "interface": source["interface"],
        "endpoint": source["endpoint"],
        "mtu": source["settings"]["mtu"],
        "dns": source["settings"]["dns"],
        "subnet": source["subnet"],
        "ipv6_subnet": source["ipv6_subnet"],
        "requires_source_ipv6": True,
        "blockers": source["blockers"],
        "warnings": [
            "endpoint_update",
            "runtime_flags",
            "routing",
            "subscriptions",
            "panel_settings",
        ],
    }


def read_wg_easy(path, source_ipv6=None):
    try:
        if source_ipv6 is not None and type(source_ipv6) is not bool:
            raise invalid()
        with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only=ON")
            for table, columns in COLUMNS.items():
                actual = {r[1] for r in db.execute(f'PRAGMA table_info("{table}")')}
                if not columns <= actual:
                    raise invalid()
            interfaces = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM interfaces_table ORDER BY name LIMIT ?", (MAX_INBOUNDS + 1,)
                )
            ]
            clients = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM clients_table ORDER BY id LIMIT ?", (MAX_CLIENTS + 1,)
                )
            ]
            config_rows = [
                dict(r)
                for r in db.execute("SELECT * FROM user_configs_table LIMIT ?", (MAX_INBOUNDS + 1,))
            ]
            hook_rows = [
                dict(r)
                for r in db.execute("SELECT * FROM hooks_table LIMIT ?", (MAX_INBOUNDS + 1,))
            ]
            configs = {r["id"]: r for r in config_rows}
            hooks = {r["id"]: r for r in hook_rows}
        if not interfaces or len(interfaces) > MAX_INBOUNDS or len(clients) > MAX_CLIENTS:
            raise invalid()
        names = {i["name"] for i in interfaces}
        if (
            len(names) != len(interfaces)
            or len(configs) != len(config_rows)
            or len(hooks) != len(hook_rows)
            or set(configs) != names
            or set(hooks) != names
            or any(c["interface_id"] not in names for c in clients)
        ):
            raise invalid()
        if len({c["id"] for c in clients}) != len(clients):
            raise invalid()
        result = []
        for index, interface in enumerate(interfaces, 1):
            config = configs[interface["name"]]
            peers = [c for c in clients if c["interface_id"] == interface["name"]]
            result.append(
                convert(index, interface, config, hooks[interface["name"]], peers, source_ipv6)
            )
        return result
    except (
        sqlite3.DatabaseError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        OverflowError,
        OSError,
    ) as exc:
        raise invalid() from exc


def convert(identifier, interface, config, hooks, peers, source_ipv6):
    name = text(interface["name"], 32)
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+", name):
        raise invalid()
    subnet = ipaddress.IPv4Network(interface["ipv4_cidr"])
    subnet6 = ipaddress.IPv6Network(interface["ipv6_cidr"])
    if not 1 <= subnet.prefixlen <= 30:
        raise invalid()
    server_key = key(interface["private_key"])
    server_public = key(interface["public_key"])
    dns = [str(ipaddress.ip_address(v)) for v in array(config["default_dns"])]
    mtu = integer(interface["mtu"], 576, 1500)
    integer(config["default_mtu"], 576, 1500)
    integer(config["default_persistent_keepalive"], 0, 65535)
    port = integer(config["port"], 1, 65535)
    integer(interface["port"], 1, 65535)
    integer(interface["enabled"], 0, 1)
    blockers = set()
    if not default_hooks(hooks):
        blockers.add("server_hooks")
    if interface.get("firewall_enabled"):
        blockers.add("firewall")
    if interface.get("routing_table", "auto") != "auto":
        blockers.add("routing_table")
    if config["default_mtu"] != mtu:
        blockers.add("client_mtu")
    if any(
        ipaddress.ip_address(v) in subnet
        if ipaddress.ip_address(v).version == 4
        else ipaddress.ip_address(v) in subnet6
        for v in dns
    ):
        blockers.add("gateway_dns")
    base_routes = [str(ipaddress.ip_network(v)) for v in array(config["default_allowed_ips"])]
    if set(base_routes) not in ({"0.0.0.0/0"}, {"0.0.0.0/0", "::/0"}):
        blockers.add("client_routes")
    counts = Counter(c["name"].lower() for c in peers if isinstance(c["name"], str))
    reserved = {
        c["name"].lower()
        for c in peers
        if isinstance(c["name"], str)
        and EMAIL.fullmatch(c["name"])
        and counts[c["name"].lower()] == 1
    }
    clients, used, public_keys = [], [], {key_bytes(server_public)}
    for peer in peers:
        peer_id = integer(peer["id"], 1, 2**53 - 1)
        original_name = text(peer["name"])
        email = original_name
        if not EMAIL.fullmatch(email) or counts[email.lower()] != 1:
            base_email = email = f"wg-easy-{name}-{peer_id}"
            suffix = 0
            while email.lower() in reserved:
                suffix += 1
                email = f"{base_email}-{suffix}"
        reserved.add(email.lower())
        address = ipaddress.IPv4Address(peer["ipv4_address"])
        address6 = ipaddress.IPv6Address(peer["ipv6_address"])
        if (
            address not in subnet
            or address
            in {subnet.network_address, subnet.broadcast_address, subnet.network_address + 1}
            or address6 not in subnet6
            or address6 in {subnet6.network_address, subnet6.network_address + 1}
        ):
            raise invalid()
        addresses = [f"{address}/32"] + ([f"{address6}/128"] if source_ipv6 is not False else [])
        for value in addresses:
            if value in used:
                raise invalid()
            used.append(value)
        public = key(peer["public_key"])
        if key_bytes(public) in public_keys:
            raise invalid()
        public_keys.add(key_bytes(public))
        private = key(peer["private_key"], optional=True)
        psk = key(peer["pre_shared_key"], optional=True)
        # A zero PSK means no preshared key, not a new secret to generate.
        if psk and key_bytes(psk) == bytes(32):
            psk = ""
        peer_dns = (
            dns
            if peer["dns"] is None
            else [str(ipaddress.ip_address(v)) for v in array(peer["dns"])]
        )
        if peer_dns != dns:
            blockers.add("client_dns")
        if integer(peer["mtu"], 576, 1500) != mtu:
            blockers.add("client_mtu")
        routes = (
            base_routes
            if peer["allowed_ips"] is None
            else [str(ipaddress.ip_network(v)) for v in array(peer["allowed_ips"])]
        )
        if set(routes) != set(base_routes):
            blockers.add("client_routes")
        if array(peer["server_allowed_ips"]):
            blockers.add("server_routes")
        if peer["server_endpoint"]:
            blockers.add("server_endpoint")
        if any(peer[k] for k in ("pre_up", "post_up", "pre_down", "post_down")):
            blockers.add("client_hooks")
        clients.append(
            {
                "email": email,
                "comment": original_name,
                "privateKey": private,
                "publicKey": public,
                "preSharedKey": psk,
                "allowedIPs": addresses,
                "keepAlive": integer(peer["persistent_keepalive"], 0, 65535),
                "enable": bool(integer(peer["enabled"], 0, 1)),
                "expiryTime": expiry(peer["expires_at"]),
                "totalGB": 0,
                "limitIp": 0,
            }
        )
    host = text(config["host"], 253)
    if not host or any(c.isspace() for c in host) or any(c in host for c in "/\\@?#"):
        raise invalid()
    source = {
        "id": identifier,
        "remark": f"wg-easy-{name}",
        "port": port,
        "interface": name,
        # wg-easy v15 does not apply interfaces_table.enabled to the running WG.
        "enable": True,
        "endpoint": {"host": host, "port": port},
        "subnet": str(subnet),
        "ipv6_subnet": str(subnet6),
        "settings": {
            "secretKey": server_key,
            "mtu": mtu,
            "dns": ",".join(dns),
            "subnetIp": str(subnet.network_address),
            "subnetCidr": subnet.prefixlen,
            "noKernelTun": True,
            "clients": clients,
            "peers": [],
        },
        "clients": clients,
        "server_public_key": server_public,
        "blockers": sorted(blockers),
    }
    source["migration"] = public_source(source)
    return source

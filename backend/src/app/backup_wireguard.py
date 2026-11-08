import base64
import ipaddress
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from app.backup_clients import FIELDS, MAX_CLIENTS, MAX_INBOUNDS
from framework.messages import MessageKey
from framework.messages import text as message_text

KEY_FIELDS = {
    "wg_private_key": "privateKey",
    "wg_public_key": "publicKey",
    "wg_pre_shared_key": "preSharedKey",
    "wg_keep_alive": "keepAlive",
}


def key_bytes(value):
    try:
        raw = (
            bytes.fromhex(value)
            if len(value) == 64
            else base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        )
        if len(raw) != 32:
            raise ValueError()
        return raw
    except (ValueError, TypeError) as exc:
        raise ValueError(message_text(MessageKey.WIREGUARD_BACKUP_INVALID)) from exc


def client_identity(client):
    result = {k: client.get(k, "") or "" for k in ("email", "subId", "comment")}
    result.update(
        {
            k: key_bytes(client[k]) if client.get(k) else None
            for k in ("privateKey", "publicKey", "preSharedKey")
        }
    )
    result["allowedIPs"] = sorted(
        str(ipaddress.ip_network(v, strict=False)) for v in client.get("allowedIPs", [])
    )
    result.update(
        keepAlive=client.get("keepAlive") or 0,
        enable=bool(client.get("enable", True)),
        totalGB=client.get("totalGB") or 0,
        expiryTime=client.get("expiryTime") or 0,
    )
    return result


def normalized_clients(db, identifier, settings):
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if {"clients", "client_inbounds"} <= tables:
        columns = {r[1] for r in db.execute("PRAGMA table_info(clients)")}
        if not {"email", "wg_public_key", "wg_allowed_ips"} <= columns:
            raise ValueError(message_text(MessageKey.WIREGUARD_BACKUP_INVALID))
        rows = db.execute(
            "SELECT c.* FROM clients c JOIN client_inbounds ci ON ci.client_id=c.id "
            "WHERE ci.inbound_id=? ORDER BY c.id LIMIT ?",
            (identifier, MAX_CLIENTS + 1),
        )
        clients = []
        embedded = {str(c.get("email", "")).lower(): c for c in settings.get("clients", [])}
        names = [d[0] for d in rows.description]
        for record in rows:
            row = dict(zip(names, record))
            client = {
                field: row[name] for name, field in {**FIELDS, **KEY_FIELDS}.items() if name in row
            }
            client["allowedIPs"] = [
                v.strip() for v in row["wg_allowed_ips"].split(",") if v.strip()
            ]
            peer = embedded.get(str(client.get("email", "")).lower())
            if peer:
                if peer.get("subId") and peer["subId"] != client.get("subId"):
                    raise ValueError(message_text(MessageKey.WIREGUARD_BACKUP_INVALID))
                for field in ("privateKey", "publicKey", "preSharedKey", "allowedIPs", "keepAlive"):
                    client[field] = peer.get(
                        field, [] if field == "allowedIPs" else 0 if field == "keepAlive" else ""
                    )
            else:
                attachments = db.execute(
                    "SELECT COUNT(*) FROM client_inbounds ci JOIN inbounds i ON i.id=ci.inbound_id WHERE ci.client_id=? AND i.protocol IN ('wireguard','amneziawg')",
                    (row["id"],),
                ).fetchone()[0]
                if attachments != 1:
                    raise ValueError(message_text(MessageKey.WIREGUARD_BACKUP_INVALID))
            client["enable"] = bool(client.get("enable", True))
            clients.append(client)
        if len(clients) > MAX_CLIENTS or (
            not clients and (settings.get("peers") or settings.get("clients"))
        ):
            raise ValueError(message_text(MessageKey.WIREGUARD_BACKUP_INVALID))
        return clients
    clients = settings.get("clients") or settings.get("peers") or []
    if not isinstance(clients, list):
        raise ValueError(message_text(MessageKey.WIREGUARD_BACKUP_INVALID))
    return clients


def read_wireguard(path, *, source_ipv6=None):
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        from app.wg_easy import TABLES, read_wg_easy

        if TABLES <= tables:
            if "inbounds" in tables:
                raise ValueError(message_text(MessageKey.WIREGUARD_BACKUP_INVALID))
            return read_wg_easy(path, source_ipv6)
        rows = db.execute(
            "SELECT id,remark,port,settings FROM inbounds WHERE protocol='wireguard' "
            "ORDER BY id LIMIT ?",
            (MAX_INBOUNDS + 1,),
        ).fetchall()
        if len(rows) > MAX_INBOUNDS:
            raise ValueError(message_text(MessageKey.WIREGUARD_BACKUP_INVALID))
        result = []
        for row in rows:
            settings = json.loads(row["settings"])
            key_bytes(settings["secretKey"])
            clients = normalized_clients(db, row["id"], settings)
            if len(clients) > MAX_CLIENTS:
                raise ValueError(message_text(MessageKey.WIREGUARD_BACKUP_INVALID))
            used = []
            for client in clients:
                key_bytes(client["publicKey"])
                for name in ("privateKey", "preSharedKey"):
                    if client.get(name):
                        key_bytes(client[name])
                if not client.get("allowedIPs"):
                    raise ValueError(message_text(MessageKey.WIREGUARD_BACKUP_INVALID))
                for value in client["allowedIPs"]:
                    network = ipaddress.ip_network(value, strict=False)
                    if any(network.version == n.version and network.overlaps(n) for n in used):
                        raise ValueError(message_text(MessageKey.WIREGUARD_BACKUP_INVALID))
                    used.append(network)
            result.append(
                {
                    "id": row["id"],
                    "remark": row["remark"],
                    "port": row["port"],
                    "settings": settings,
                    "clients": clients,
                }
            )
        return result


def select_wireguard(path, identifier, *, source_ipv6=None):
    source = next(
        (row for row in read_wireguard(path, source_ipv6=source_ipv6) if row["id"] == identifier),
        None,
    )
    if source is None:
        raise ValueError(message_text(MessageKey.WIREGUARD_BACKUP_INVALID))
    migration = source.get("migration")
    if migration:
        if migration["blockers"]:
            raise ValueError(
                message_text(
                    MessageKey.WG_EASY_UNSUPPORTED, fields=", ".join(migration["blockers"])
                )
            )
        if type(source_ipv6) is not bool:
            raise ValueError(message_text(MessageKey.WG_EASY_IPV6_REQUIRED))
    elif source_ipv6 is not None:
        raise ValueError(message_text(MessageKey.WIREGUARD_BACKUP_INVALID))
    return source


def public_catalog(rows):
    return [
        {
            "id": row["id"],
            "remark": row["remark"],
            "port": row["port"],
            "client_count": len(row["clients"]),
            "clients": [
                {
                    "email": c.get("email", ""),
                    "has_private_key": bool(c.get("privateKey")),
                    **(
                        {
                            "name": c.get("comment", ""),
                            "enabled": c.get("enable", True),
                            "addresses": c.get("allowedIPs", []),
                            "expiry_time": c.get("expiryTime", 0),
                        }
                        if row.get("migration")
                        else {}
                    ),
                }
                for c in row["clients"]
            ],
            **row.get("migration", {}),
        }
        for row in rows
    ]

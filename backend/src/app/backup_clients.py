"""Read 3x-ui SQLite client identities without mutating the backup.

Shared by the local backup preview and the stdlib-only SSH agent. Never log the
private return value; only public_catalog() can cross the HTTP/UI boundary.
In 3x-ui 3.11 the normalized clients/client_inbounds tables are authoritative.
"""

import json
import re
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path

MAX_INBOUNDS = 100
MAX_CLIENTS = 3000
EMAIL = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.@-]{0,79}$")
SUB_ID = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")

# Metadata safe to carry into a different panel, without copying host bindings
# or provider-specific keys. UUID and subscription ID are mandatory.
FIELDS = {
    "email": "email",
    "sub_id": "subId",
    "uuid": "id",
    "flow": "flow",
    "enable": "enable",
    "limit_ip": "limitIp",
    "total_gb": "totalGB",
    "expiry_time": "expiryTime",
    "comment": "comment",
    "group_name": "group",
    "tg_id": "tgId",
    "reset": "reset",
    "reset_day": "resetDay",
    "reset_weekday": "resetWeekday",
    "reset_max": "resetMax",
    "traffic_reset": "trafficReset",
    "traffic_reset_day": "trafficResetDay",
}


def _object(value):
    if isinstance(value, str):
        value = json.loads(value or "{}")
    if not isinstance(value, dict):
        raise ValueError("Invalid source client settings")
    return value


def _ready(value):
    try:
        return (
            isinstance(value.get("email"), str)
            and EMAIL.fullmatch(value["email"]) is not None
            and isinstance(value.get("subId"), str)
            and SUB_ID.fullmatch(value["subId"]) is not None
            and isinstance(value.get("id"), str)
            and str(uuid.UUID(value["id"])) == value["id"].lower()
        )
    except (ValueError, TypeError, KeyError):
        return False


def _append(items, source_id, remark, protocol, reference, client):
    target = items.setdefault(
        source_id,
        {"id": source_id, "remark": remark, "protocol": protocol, "clients": []},
    )
    if len(target["clients"]) >= MAX_CLIENTS:
        raise ValueError("Client catalog limit reached")
    client = dict(client)
    target["clients"].append(
        {
            "ref": reference,
            "email": str(client.get("email") or "")[:160],
            "enabled": bool(client.get("enable", True)),
            "has_subscription": bool(client.get("subId")),
            "restorable": _ready(client),
            "data": client,
        }
    )


def read_catalog(path):
    """Return private client records from a validated, read-only SQLite backup."""
    found = {}
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "inbounds" not in tables:
            raise ValueError("Missing source inbounds")
        sources = db.execute(
            "SELECT id,remark,protocol,settings FROM inbounds ORDER BY id LIMIT ?",
            (MAX_INBOUNDS + 1,),
        ).fetchall()
        if len(sources) > MAX_INBOUNDS:
            raise ValueError("Too many source inbounds")
        for row in sources:
            if row["protocol"] == "vless":
                found[row["id"]] = {
                    "id": row["id"],
                    "remark": str(row["remark"] or "")[:160],
                    "protocol": "vless",
                    "clients": [],
                }
        if {"clients", "client_inbounds"} <= tables:
            # IMPORTANT: in 3x-ui 3.11 the embedded inbounds.settings JSON
            # can contain stale identities. Read the normalized tables instead.
            required_clients = {"id", "email", "sub_id", "uuid"}
            actual = {r[1] for r in db.execute("PRAGMA table_info(clients)")}
            relation = {r[1] for r in db.execute("PRAGMA table_info(client_inbounds)")}
            if not required_clients <= actual or not {"client_id", "inbound_id"} <= relation:
                raise ValueError("Unsupported normalized clients schema")
            flow_override = "ci.flow_override" if "flow_override" in relation else "''"
            rows = db.execute(
                "SELECT i.id AS source_inbound_id, c.*, "
                + flow_override
                + " AS selected_flow FROM inbounds i "
                "JOIN client_inbounds ci ON ci.inbound_id=i.id "
                "JOIN clients c ON c.id=ci.client_id "
                "WHERE i.protocol='vless' ORDER BY i.id,c.id LIMIT ?",
                (MAX_CLIENTS + 1,),
            ).fetchall()
            if len(rows) > MAX_CLIENTS:
                raise ValueError("Too many source clients")
            for row in rows:
                source = found.get(row["source_inbound_id"])
                if source is None:
                    continue
                client = {field: row[name] for name, field in FIELDS.items() if name in actual}
                if isinstance(row["selected_flow"], str) and row["selected_flow"]:
                    client["flow"] = row["selected_flow"]
                _append(
                    found,
                    source["id"],
                    source["remark"],
                    "vless",
                    "n:" + str(row["id"]),
                    client,
                )
        else:
            count = 0
            for row in sources:
                if row["protocol"] != "vless":
                    continue
                settings = _object(row["settings"])
                clients = settings.get("clients", [])
                if not isinstance(clients, list):
                    raise ValueError("Invalid legacy client list")
                for index, client in enumerate(clients):
                    if not isinstance(client, dict):
                        raise ValueError("Invalid legacy client entry")
                    count += 1
                    if count > MAX_CLIENTS:
                        raise ValueError("Too many source clients")
                    # Use only attributes supported by the 3x-ui client API.
                    safe = {name: client[name] for name in FIELDS.values() if name in client}
                    _append(
                        found,
                        row["id"],
                        str(row["remark"] or "")[:160],
                        "vless",
                        "l:" + str(index),
                        safe,
                    )
    return list(found.values())


def public_catalog(private_catalog):
    """Never return UUIDs, subIds, secrets or raw settings to the browser."""
    return {
        "inbounds": [
            {
                "id": source["id"],
                "remark": source["remark"],
                "protocol": source["protocol"],
                "client_count": len(source["clients"]),
                "clients": [
                    {
                        key: item[key]
                        for key in ("ref", "email", "enabled", "has_subscription", "restorable")
                    }
                    for item in source["clients"]
                ],
            }
            for source in private_catalog
        ]
    }


def select_clients(private_catalog, inbound_id, refs):
    if not refs or len(refs) > 100 or len(refs) != len(set(refs)):
        raise ValueError("Invalid selected client references")
    sources = [s for s in private_catalog if s["id"] == inbound_id]
    if len(sources) != 1:
        raise ValueError("Source inbound was not found")
    by_ref = {c["ref"]: c for c in sources[0]["clients"]}
    if len(by_ref) != len(sources[0]["clients"]):
        raise ValueError("Ambiguous source clients")
    if any(ref not in by_ref or not by_ref[ref]["restorable"] for ref in refs):
        raise ValueError("Client has missing/invalid subscription ID or UUID")
    selected = [dict(by_ref[ref]["data"]) for ref in refs]
    emails = [c["email"].lower() for c in selected]
    sub_ids = [c["subId"] for c in selected]
    uuids = [c["id"].lower() for c in selected]
    if (
        len(set(emails)) != len(emails)
        or len(set(sub_ids)) != len(sub_ids)
        or len(set(uuids)) != len(uuids)
    ):
        raise ValueError("Duplicate client identity in selected source")
    return selected

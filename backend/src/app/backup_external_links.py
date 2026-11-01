"""Read 3x-ui subscription aggregation edges without exposing their bearer tokens.

The first recovery version supports only same-panel HTTPS subscription URLs
whose subId belongs to an account in the source dump. Third-party links and
raw share links are never auto-adopted: 3x-ui may fetch remote subscriptions.
"""

import ipaddress
from collections import defaultdict
from urllib.parse import urlsplit

from framework.messages import MessageKey
from framework.messages import text as message_text

MAX_LINKS = 5000
MAX_LINKS_PER_CLIENT = 64
MAX_URL_BYTES = 2048


def invalid():
    raise ValueError(message_text(MessageKey.BACKUP_CLIENTS_INVALID))


def source_subscription_uri(db):
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "settings" not in tables:
        return None
    row = db.execute("SELECT value FROM settings WHERE key='subURI' LIMIT 1").fetchone()
    if not row or not isinstance(row[0], str):
        return None
    value = row[0].strip()
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    if parsed.query or parsed.fragment or any(ord(c) < 33 for c in value):
        return None
    return value.rstrip("/") + "/"


def _public_https(value):
    if not isinstance(value, str) or len(value.encode("utf-8")) > MAX_URL_BYTES:
        return False
    try:
        parts = urlsplit(value)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.query
            or parts.fragment
            or any(ord(ch) <= 32 for ch in value)
        ):
            return False
        host = parts.hostname
        if host.lower() == "localhost" or host.endswith(".local"):
            return False
        try:
            if not ipaddress.ip_address(host).is_global:
                return False
        except ValueError:
            # Public DNS hostname; the 3x-ui fetcher remains responsible for
            # its own DNS rebinding, redirects and network-access policies.
            if "." not in host or host.endswith(".internal"):
                return False
        _ = parts.port
        return True
    except (ValueError, UnicodeError):
        return False


def read_external_links(db, subscriber_ids):
    """Return {client_pk: links} and the old public subscription base URI."""
    columns = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "client_external_links" not in columns:
        return {}, None
    fields = {row[1] for row in db.execute("PRAGMA table_info(client_external_links)")}
    required = {
        "id", "client_id", "kind", "value", "remark", "enable",
        "expiry_time", "name_prefix", "sort_index",
    }
    if not required <= fields:
        invalid()
    base = source_subscription_uri(db)
    rows = db.execute(
        "SELECT id,client_id,kind,value,remark,enable,expiry_time,name_prefix "
        "FROM client_external_links ORDER BY client_id,sort_index,id LIMIT ?",
        (MAX_LINKS + 1,),
    ).fetchall()
    if len(rows) > MAX_LINKS:
        invalid()
    links = defaultdict(list)
    for row in rows:
        owner = row["client_id"]
        if owner not in subscriber_ids:
            # An orphaned link must not be silently reattached to another
            # account after the database is imported.
            continue
        if len(links[owner]) >= MAX_LINKS_PER_CLIENT:
            invalid()
        value = row["value"]
        valid_url = _public_https(value)
        ref_sub_id = None
        if valid_url and base and value.startswith(base):
            suffix = value[len(base):]
            if suffix in subscriber_ids.values():
                ref_sub_id = suffix
        kind = row["kind"]
        expiry = row["expiry_time"]
        enabled = row["enable"]
        compatible = (
            kind == "subscription" and valid_url and ref_sub_id is not None
            and isinstance(expiry, int) and expiry >= 0
            and enabled in (0, 1)
            and isinstance(row["remark"], str) and len(row["remark"]) <= 256
            and isinstance(row["name_prefix"], str) and len(row["name_prefix"]) <= 256
        )
        links[owner].append({
            "kind": kind,
            "value": value,
            "remark": row["remark"] or "",
            "enable": bool(enabled),
            "expiryTime": expiry,
            "namePrefix": row["name_prefix"] or "",
            "_ref_sub_id": ref_sub_id,
            "_compatible": compatible,
        })
    return dict(links), base


def source_dependencies(selected, catalog, target_records):
    """Reject unresolved subscription dependencies before the first mutation."""
    source_by_sub = {}
    for source in catalog:
        for item in source["clients"]:
            data = item["data"]
            source_by_sub[data["subId"]] = data
    chosen = {client["subId"] for client in selected}
    target_by_sub = {row.get("subId"): row for row in target_records}
    relations = {}
    for client in selected:
        edges = []
        for link in client.get("_external_links", []):
            if not link["_compatible"]:
                invalid()
            sub_id = link["_ref_sub_id"]
            referenced = source_by_sub.get(sub_id)
            if referenced is None:
                invalid()
            if sub_id not in chosen:
                current = target_by_sub.get(sub_id)
                if (
                    not isinstance(current, dict)
                    or str(current.get("email", "")).lower() != referenced["email"].lower()
                    or str(current.get("uuid") or current.get("id") or "").lower()
                    != referenced["id"].lower()
                ):
                    raise ValueError(message_text(MessageKey.CLIENT_EXTERNAL_DEPENDENCY))
            edges.append(sub_id)
        relations[client["subId"]] = edges
    visiting = set()
    visited = set()

    def visit(node):
        if node in visiting:
            raise ValueError(message_text(MessageKey.CLIENT_EXTERNAL_CYCLE))
        if node in visited:
            return
        visiting.add(node)
        for target in relations.get(node, []):
            visit(target)
        visiting.remove(node)
        visited.add(node)

    for node in relations:
        visit(node)
    return sum(len(v) for v in relations.values())

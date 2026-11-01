"""Scoped sync of 3x-ui external subscription links after client recovery.

3x-ui's /clients/:email/externalLinks endpoint REPLACES all rows.  For
existing accounts we first read and preserve their complete current link set,
add only missing same-panel subscription URLs and reject conflicting metadata.
The caller owns the SQLite snapshot and transaction-like compensation.
"""

from urllib.parse import quote

from app.backup_external_links import source_dependencies
from framework.messages import MessageKey
from framework.messages import text as message_text

MAX_LINKS_PER_CLIENT = 64
FIELDS = ("kind", "value", "remark", "enable", "expiryTime", "namePrefix")


def _conflict():
    raise RuntimeError(message_text(MessageKey.CLIENT_EXTERNAL_CONFLICT))


def _canonical(items):
    if not isinstance(items, list) or len(items) > MAX_LINKS_PER_CLIENT:
        _conflict()
    result = []
    seen = set()
    for value in items:
        if not isinstance(value, dict):
            _conflict()
        kind = value.get("kind")
        url = value.get("value")
        if (
            kind not in {"subscription", "link"}
            or not isinstance(url, str)
            or not url
            or len(url) > 2048
            or any(ord(ch) < 33 for ch in url)
        ):
            _conflict()
        key = (kind, url)
        if key in seen:
            _conflict()
        seen.add(key)
        enable = value.get("enable")
        if enable is None:
            enable = True
        expiry = value.get("expiryTime", 0)
        if (
            not isinstance(enable, bool)
            or isinstance(expiry, bool)
            or not isinstance(expiry, int)
            or expiry < 0
        ):
            _conflict()
        remark = value.get("remark", "")
        prefix = value.get("namePrefix", "")
        if not isinstance(remark, str) or not isinstance(prefix, str):
            _conflict()
        result.append(
            {
                "kind": kind,
                "value": url,
                "remark": remark,
                "enable": enable,
                "expiryTime": expiry,
                "namePrefix": prefix,
            }
        )
    return result


def _current_details(api, email, expected):
    """Read a full authoritative account; never infer links from /clients/list."""
    value = api.request("clients/get/" + quote(email, safe=""))
    if not isinstance(value, dict) or not isinstance(value.get("client"), dict):
        _conflict()
    client = value["client"]
    actual = (
        str(client.get("email", "")).lower(),
        str(client.get("uuid") or client.get("id") or "").lower(),
        client.get("subId"),
    )
    if actual != (expected["email"].lower(), expected["id"].lower(), expected["subId"]):
        _conflict()
    if "externalLinks" not in value:
        _conflict()
    return _canonical(value["externalLinks"])


def _merge(before, incoming):
    existing = {(item["kind"], item["value"]): item for item in before}
    result = list(before)
    added = 0
    for item in incoming:
        key = (item["kind"], item["value"])
        if key in existing:
            if existing[key] != item:
                _conflict()
            continue
        existing[key] = item
        result.append(item)
        added += 1
    if len(result) > MAX_LINKS_PER_CLIENT:
        _conflict()
    return result, added


def subscription_target(context):
    """The public subscription root, never the internal Xray listener."""
    node = context.node
    caddy = node.get("caddy") or {}
    panel = node.get("panel") or {}
    if not caddy.get("enabled") or not caddy.get("domain") or not caddy.get("https_port"):
        raise RuntimeError(message_text(MessageKey.CLIENT_EXTERNAL_PUBLIC_URL))
    path = str(panel.get("subscription_path") or "").strip()
    if not path.startswith("/"):
        raise RuntimeError(message_text(MessageKey.CLIENT_EXTERNAL_PUBLIC_URL))
    return f"https://{caddy['domain']}:{caddy['https_port']}{path.rstrip('/')}/"


def build_sync_plan(context, api, catalog, selected, existing, pending):
    """Validate all source URLs, referenced accounts and destination identity."""
    links_count = sum(len(x.get("_external_links", [])) for x in selected)
    if not links_count:
        return [], 0
    source_uri = next(
        (client.get("_source_sub_uri") for client in selected if client.get("_external_links")),
        None,
    )
    if source_uri != subscription_target(context):
        raise RuntimeError(message_text(MessageKey.CLIENT_EXTERNAL_PUBLIC_URL))
    try:
        source_dependencies(selected, catalog, existing)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc

    pending_emails = {client["email"].lower() for client in pending}
    plans, total_new = [], 0
    for client in selected:
        source_links = client.get("_external_links", [])
        if not source_links:
            continue
        originals = [{key: value[key] for key in FIELDS} for value in source_links]
        incoming = _canonical(originals)
        is_new = client["email"].lower() in pending_emails
        before = [] if is_new else _current_details(api, client["email"], client)
        desired, new_links = _merge(before, incoming)
        if new_links:
            plans.append(
                {
                    "email": client["email"],
                    "client": client,
                    "new": is_new,
                    "before": before,
                    "desired": desired,
                    "added": new_links,
                }
            )
            total_new += new_links
    return plans, total_new


def synchronize_links(api, plans, attempted):
    """Apply ordered append-only updates; attempted list supports rollback."""
    for plan in plans:
        email = plan["email"]
        current = _current_details(api, email, plan["client"])
        if current != plan["before"]:
            _conflict()
        attempted.append(plan)
        api.request(
            "clients/" + quote(email, safe="") + "/externalLinks",
            {"externalLinks": plan["desired"]},
        )
        if _current_details(api, email, plan["client"]) != plan["desired"]:
            _conflict()


def rollback_links(api, attempted, emit):
    """Restore original links only if the current set is still exactly ours."""
    for plan in reversed(attempted):
        if plan["new"]:
            # The importer will delete this whole newly created identity.
            continue
        try:
            current = _current_details(api, plan["email"], plan["client"])
            if current == plan["before"]:
                continue
            if current != plan["desired"]:
                _conflict()
            api.request(
                "clients/" + quote(plan["email"], safe="") + "/externalLinks",
                {"externalLinks": plan["before"]},
            )
            if _current_details(api, plan["email"], plan["client"]) != plan["before"]:
                _conflict()
        except Exception:
            emit(message_text(MessageKey.DEPLOYMENT_ROLLBACK_FAILED), "error")

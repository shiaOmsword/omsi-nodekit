"""Guarded subscription audit and honest server-side cache reset for 3x-ui 3.11.

An HTTP request or Xray reload DOES NOT invalidate the Go process' 5-minute
external subscription cache. Only a scoped restart of the *owned panel process*
is offered as a manual hard reset. Never touch shared Caddy or system DNS.
"""

import base64
import binascii
import json
import re
import socket
import sqlite3
import ssl
import time
import urllib.error
import urllib.request
from contextlib import closing
from urllib.parse import quote, urlsplit

from framework.messages import MessageKey
from framework.messages import text as message_text

from .inbound_manager import managed_api
from .inbound_meta import public_inbound
from .subscriptions import public_base

MAX_SUB_BODY = 1024 * 1024
MAX_RESOLVED = 5
MAX_AUDIT_SECONDS = 15
HOSTED_SUB_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def share_link_count(body):
    """Count links without returning any bearer payload or proxy credentials."""
    if len(body) > MAX_SUB_BODY:
        raise ValueError()
    text = body.decode("utf-8", errors="replace").strip()
    if not text:
        return 0
    compact = "".join(text.split())
    if re.fullmatch(r"[A-Za-z0-9_+/=-]+", compact or ""):
        try:
            decoded = base64.b64decode(compact + "=" * (-len(compact) % 4), validate=True)
            if b"://" in decoded:
                text = decoded.decode("utf-8", errors="replace")
        except (ValueError, binascii.Error):
            pass
    return sum(
        1
        for line in text.splitlines()
        if re.match(r"^(?:vless|vmess|trojan|ss|hysteria2?|tuic)://", line.strip())
    )


def public_subscription_probe(context, sub_id):
    """TLS-verified HTTPS GET; redirect refusal; never log request path or body."""
    url = public_base(context.node) + sub_id
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError()
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        NoRedirect(),
    )
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "v2rayNG/1.0", "Accept": "text/plain"},
    )
    with opener.open(
        request, timeout=min(MAX_AUDIT_SECONDS, context.policy["http_timeout"])
    ) as response:
        length = response.headers.get("Content-Length")
        if length and int(length) > MAX_SUB_BODY:
            raise ValueError()
        content = response.read(MAX_SUB_BODY + 1)
        if len(content) > MAX_SUB_BODY:
            raise ValueError()
        cache_control = response.headers.get("Cache-Control", "absent")
        if not re.fullmatch(r"[\w\s,=\-]{1,96}", cache_control or ""):
            cache_control = "unrecognized"
        return response.status, share_link_count(content), cache_control


def dns_resolve(host):
    """System-resolver observation, not a change to DNS or client caches."""
    results = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    addresses = []
    for item in results:
        address = item[4][0]
        if address not in addresses:
            addresses.append(address)
        if len(addresses) >= MAX_RESOLVED:
            break
    return addresses


def nested_subscription_stats(database, email):
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        rows = {v[0] for v in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"clients", "client_external_links"} <= rows:
            return 0, 0
        count, failures = db.execute(
            "SELECT COUNT(*), SUM(CASE WHEN COALESCE(e.last_fetch_error,'') != '' THEN 1 ELSE 0 END) "
            "FROM client_external_links e JOIN clients c ON c.id=e.client_id "
            "WHERE c.email=? AND e.kind='subscription' AND e.enable=1",
            (email,),
        ).fetchone()
        return int(count or 0), int(failures or 0)


def verify_client(api, inbound_id, email):
    if not email:
        return None
    result = api.request("clients/get/" + quote(email, safe=""))
    if not isinstance(result, dict):
        raise RuntimeError(message_text(MessageKey.SUB_CACHE_CLIENT_INVALID))
    client = result.get("client")
    membership = result.get("inboundIds")
    if (
        not isinstance(client, dict)
        or not isinstance(membership, list)
        or inbound_id not in membership
        or str(client.get("email", "")).lower() != email.lower()
        or not isinstance(client.get("subId"), str)
        or not HOSTED_SUB_ID.fullmatch(client["subId"])
    ):
        raise RuntimeError(message_text(MessageKey.SUB_CACHE_CLIENT_INVALID))
    return client["subId"]


def owned_panel_container(context, inspector):
    """Require 3 independent ownership proofs before any restart."""
    selected = inspector.selected or {}
    container = selected.get("container")
    if selected.get("installation") != "managed" or not container:
        raise RuntimeError(message_text(MessageKey.SUB_CACHE_RESTART_GUARD))
    if (context.node.get("deployment") or {}).get("panel_runtime") != "docker":
        raise RuntimeError(message_text(MessageKey.SUB_CACHE_RESTART_GUARD))
    try:
        result = json.loads(context.command(["docker", "inspect", container]))
        info = result[0] if isinstance(result, list) and len(result) == 1 else {}
        labels = (info.get("Config") or {}).get("Labels") or {}
        identifier = str(info.get("Id") or "")
        if (
            not identifier
            or selected.get("id") != "docker:" + identifier
            or labels.get("com.docker.compose.project") != context.project()
            or labels.get("com.docker.compose.service") != "panel"
            or not (info.get("State") or {}).get("Running")
        ):
            raise ValueError()
        return identifier
    except (OSError, ValueError, TypeError, IndexError, RuntimeError) as exc:
        raise RuntimeError(message_text(MessageKey.SUB_CACHE_RESTART_GUARD)) from exc


class SubscriptionMaintenanceAgent:
    def __init__(self, context, host, database, inspector):
        self.context, self.host, self.database, self.inspector = context, host, database, inspector

    def apply(self, base):
        context = self.context
        request = context.payload["options"]["subscription_maintenance"]
        api = managed_api(context, self.inspector, base)
        item = api.request(f"inbounds/get/{request['id']}")
        if (
            not isinstance(item, dict)
            or item.get("protocol") != "vless"
            or public_inbound(item)["fingerprint"] != request["expected_fingerprint"]
        ):
            raise RuntimeError(message_text(MessageKey.INBOUND_STALE))
        sub_id = verify_client(api, request["id"], request.get("client_email"))
        selected = self.inspector.selected
        if not selected or not selected.get("active"):
            raise RuntimeError(message_text(MessageKey.INSPECTION_REQUIRED))
        # Refuse a shared/foreign Docker container before any I/O that could mutate services.
        container_id = None
        if request["mode"] == "clear_server_cache":
            if request.get("acknowledge_restart") is not True:
                raise RuntimeError(message_text(MessageKey.SUB_CACHE_REQUEST_INVALID))
            container_id = owned_panel_container(context, self.inspector)
        self.audit(api, sub_id, request.get("client_email"))
        if request["mode"] == "audit":
            context.emit(message_text(MessageKey.SUB_CACHE_AUDIT_COMPLETE))
            return
        # Restart deliberately clears both short-lived 3x-ui caches, at a cost:
        # the panel and its child Xray process may briefly disconnect VPN users.
        snapshot = base / f"before-sub-cache-reset-{time.time_ns()}.db"
        self.database.snapshot(self.inspector.database(), snapshot)
        context.emit(message_text(MessageKey.SUB_CACHE_RESTART_STARTED), "warning")
        context.command(
            ["docker", "restart", "--time", "10", container_id],
            timeout=context.policy["startup_timeout"],
        )
        for _ in range(25):
            try:
                if self.host.port_open(context.node["panel"]["port"]):
                    after = api.request(f"inbounds/get/{request['id']}")
                    if (
                        isinstance(after, dict)
                        and public_inbound(after)["fingerprint"] == request["expected_fingerprint"]
                    ):
                        context.emit(message_text(MessageKey.SUB_CACHE_RESTART_OK))
                        return
            except RuntimeError:
                pass
            time.sleep(1)
        raise RuntimeError(message_text(MessageKey.SUB_CACHE_RESTART_FAILED))

    def audit(self, api, sub_id, email):
        context = self.context
        node = context.node
        selected = self.inspector.selected or {}
        settings = selected.get("settings", {})
        expected = public_base(node) if node["caddy"]["enabled"] else ""
        if not expected or settings.get("subURI") != expected:
            context.emit(message_text(MessageKey.SUB_CACHE_PUBLIC_URL_MISMATCH), "warning")
        domain = node["caddy"].get("domain") if node["caddy"]["enabled"] else None
        if domain:
            try:
                addresses = dns_resolve(domain)
                context.emit(
                    message_text(
                        MessageKey.SUB_CACHE_DNS_CHECK,
                        host=domain,
                        addresses=", ".join(addresses) or "no records",
                    ),
                )
            except (OSError, ValueError):
                context.emit(message_text(MessageKey.SUB_CACHE_DNS_FAILED), "warning")
        if sub_id and expected:
            try:
                status, count, cache_control = public_subscription_probe(context, sub_id)
                level = "info" if count > 0 and status == 200 else "warning"
                context.emit(
                    message_text(
                        MessageKey.SUB_CACHE_TLS_OK,
                        status=status,
                        count=count,
                        cache_control=cache_control,
                    ),
                    level,
                )
            except (urllib.error.URLError, OSError, ValueError, ssl.SSLError, TimeoutError):
                context.emit(message_text(MessageKey.SUB_CACHE_TLS_FAILED), "warning")
        if email:
            try:
                count, failures = nested_subscription_stats(self.inspector.database(), email)
                context.emit(
                    message_text(
                        MessageKey.SUB_CACHE_EXTERNAL_STATUS, count=count, failed=failures
                    ),
                    "warning" if failures else "info",
                )
            except (sqlite3.DatabaseError, OSError, ValueError):
                context.emit(message_text(MessageKey.SUB_CACHE_TLS_FAILED), "warning")

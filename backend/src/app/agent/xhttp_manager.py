"""Manage Nodekit-owned VLESS/XHTTP ingress through 3x-ui and shared Caddy.

No unowned Caddy sites, Docker containers, or unrelated firewall rules are modified.
The remote agent stays stdlib-only. Secrets never appear in reports.
"""

import copy
import fnmatch
import json
import secrets
import time
import uuid

from framework.messages import MessageKey
from framework.messages import text as message_text

from .caddy_reuse import ExistingCaddy
from .firewall import (
    FirewallTransaction,
    caddy_matches,
    desired_rules,
    reserved_caddy_ports,
    rule_spec,
)
from .inbound_manager import configuration, identities, managed_api, matches_update
from .inbound_meta import object_value, public_inbound
from .tunnel_manager import private_write


def load_routes(base):
    path = base / "xhttp-routes.json"
    if path.is_symlink():
        raise ValueError(message_text(MessageKey.DEPLOYMENT_CADDY_CHANGED))
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
    if not isinstance(data, list) or any(not isinstance(r, dict) for r in data):
        raise ValueError(message_text(MessageKey.DEPLOYMENT_CADDY_UNSAFE))
    return data


def site_for(route):
    # Domain and path are already strictly validated at the Pydantic boundary.
    return (
        f"{route['domain']} {{\n"
        f"    @nodekit_xhttp path {route['path']}*\n"
        f"    handle @nodekit_xhttp {{\n"
        f"        reverse_proxy h2c://{route['listen']}:{route['port']} {{\n"
        f"            flush_interval -1\n"
        f"        }}\n"
        f"    }}\n"
        f"    handle {{\n"
        f'        respond "OK" 200\n'
        f"    }}\n"
        f"}}\n"
    )


def render_managed_site(subscriptions_site, routes):
    return (
        subscriptions_site.rstrip()
        + "\n"
        + ("\n" + "\n".join(site_for(r) for r in routes) if routes else "")
    )


class XHTTPManager:
    def __init__(self, context, host, database, inspector):
        self.context, self.host, self.database, self.inspector = context, host, database, inspector

    def apply(self, base):
        request = self.context.payload["options"]["xhttp"]
        node = self.context.node
        target = node.get("deployment") or {}
        if (
            target.get("caddy_mode") != "existing"
            or not node["caddy"]["enabled"]
            or not node["panel"]["installation"] == "managed"
            or base.is_symlink()
        ):
            raise RuntimeError(message_text(MessageKey.INBOUND_MANAGED_REQUIRED))
        api = managed_api(self.context, self.inspector, base)
        if request["operation"] == "publish":
            return self.publish_host(base, api, request)
        manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))["node"]
        if (
            manifest["id"] != node["id"]
            or manifest.get("deployment", {}).get("caddy_mode") != "existing"
        ):
            raise RuntimeError(message_text(MessageKey.SUBSCRIPTION_CONFIGURE_GUARD))
        site_path = base / "Caddyfile.site"
        routes_path = base / "xhttp-routes.json"
        if site_path.is_symlink():
            raise RuntimeError(message_text(MessageKey.DEPLOYMENT_CADDY_UNSAFE))
        previous_site = site_path.read_bytes()
        routes = load_routes(base)
        if request["domain"].lower() == node["caddy"]["domain"].lower():
            raise RuntimeError(message_text(MessageKey.DEPLOYMENT_CADDY_COLLISION))
        if any(
            r["domain"].lower() == request["domain"].lower()
            and (request["operation"] == "create" or r["id"] != request["id"])
            for r in routes
        ):
            raise RuntimeError(message_text(MessageKey.DEPLOYMENT_CADDY_COLLISION))

        caddy = ExistingCaddy(self.context, self.inspector)
        caddy.preflight(previous_site, manifest["caddy"]["domain"])
        existing = next((r for r in routes if r["id"] == request.get("id")), None)
        if request["operation"] == "update" and not existing:
            raise RuntimeError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
        # Refuse adopting any existing or wildcard third-party hostname. On
        # update, the prior owned hostname is already included in previous_site.
        for route in caddy.finding.get("routes", []):
            if (
                existing
                and any(h.lower() == existing["domain"].lower() for h in route.get("hosts", []))
                and request["domain"].lower() == existing["domain"].lower()
            ):
                continue
            if any(
                fnmatch.fnmatchcase(request["domain"].lower(), h.lower())
                or fnmatch.fnmatchcase(h.lower(), request["domain"].lower())
                for h in route.get("hosts", [])
            ):
                raise RuntimeError(message_text(MessageKey.DEPLOYMENT_CADDY_COLLISION))

        bind = target["subscription_bind"]
        bridges = [
            n
            for proxy in self.inspector.report.get("caddy", [])
            if caddy_matches(proxy, target["caddy_id"])
            for n in proxy.get("bridge_networks", [])
            if n.get("gateway") == bind
        ]
        if bind != "127.0.0.1" and len(bridges) != 1:
            raise RuntimeError(message_text(MessageKey.DEPLOYMENT_BIND_INVALID))
        other_inbounds = api.request("inbounds/list") or []
        if (
            request["port"] in {node["panel"]["port"], node["panel"]["subscription_port"]}
            or request["port"] in reserved_caddy_ports(self.inspector.report)
            or any(
                item["port"] == request["port"] and item["id"] != request.get("id")
                for item in other_inbounds
            )
        ):
            raise RuntimeError(message_text(MessageKey.DEPLOYMENT_INBOUND_COLLISION))

        before = None
        if request["operation"] == "create":
            self.host.require_endpoint(request["port"], bind)
            client = {
                "id": str(uuid.uuid4()),
                "subId": secrets.token_urlsafe(18),
                "email": request.get("client_email") or "client-xhttp",
                "enable": True,
                "flow": "",
                "limitIp": 0,
                "totalGB": 0,
                "expiryTime": 0,
            }
            proposed = {
                "remark": request["remark"],
                "enable": True,
                "listen": bind,
                "port": request["port"],
                "protocol": "vless",
                "settings": {"clients": [client], "decryption": "none", "fallbacks": []},
                "streamSettings": {
                    "network": "xhttp",
                    "security": "none",
                    "xhttpSettings": {"host": "", "path": request["path"], "mode": request["mode"]},
                },
                "sniffing": {
                    "enabled": True,
                    "destOverride": ["http", "tls", "quic"],
                    "routeOnly": True,
                },
                "allocate": {"strategy": "always", "refresh": 5, "concurrency": 3},
            }
            operation_data = {
                k: json.dumps(v) if isinstance(v, dict) else v for k, v in proposed.items()
            }
        else:
            before = api.request(f"inbounds/get/{request['id']}")
            if public_inbound(before)["fingerprint"] != request["expected_fingerprint"]:
                raise RuntimeError(message_text(MessageKey.INBOUND_STALE))
            stream = object_value(before.get("streamSettings"))
            if (
                before.get("protocol") != "vless"
                or stream.get("network") != "xhttp"
                or stream.get("security") != "none"
                or before.get("listen") != existing["listen"]
                or before["port"] != existing["port"]
            ):
                raise RuntimeError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
            if request["port"] != before["port"]:
                self.host.require_endpoint(request["port"], bind)
            proposed = copy.deepcopy(before)
            proposed.update(remark=request["remark"], port=request["port"])
            stream.setdefault("xhttpSettings", {}).update(
                path=request["path"], mode=request["mode"]
            )
            proposed["streamSettings"] = stream
            operation_data = proposed

        if before and configuration(api.request(f"inbounds/get/{request['id']}")) != configuration(
            before
        ):
            raise RuntimeError(message_text(MessageKey.INBOUND_STALE))
        self.database.snapshot(
            self.inspector.database(), base / f"before-xhttp-{time.time_ns()}.db"
        )
        fw = FirewallTransaction(self.context, base, enabled=target.get("manage_ufw", True))
        extra = []
        if bridges:
            b = bridges[0]
            extra = [
                rule_spec(
                    request["port"],
                    source=b["subnet"],
                    destination=bind,
                    interface=b["interface"],
                    scope="xhttp",
                )
            ]
        written = {}
        snapshot_files = {
            p: p.read_bytes() if p.exists() else None for p in (site_path, routes_path)
        }
        changed_id = None
        try:
            fw.ensure(desired_rules(self.context, self.inspector.report, extra=extra))
            if request["operation"] == "create":
                if any(
                    i.get("remark") == request["remark"]
                    for i in (api.request("inbounds/list") or [])
                ):
                    raise RuntimeError(message_text(MessageKey.DEPLOYMENT_INBOUND_COLLISION))
                response = api.request("inbounds/add", operation_data)
                identifier = response.get("id") if isinstance(response, dict) else None
                if not isinstance(identifier, int) or identifier <= 0:
                    raise RuntimeError(message_text(MessageKey.DEPLOYMENT_API_FAILED))
            else:
                identifier = request["id"]
                api.request(f"inbounds/update/{identifier}", operation_data)
            changed_id = identifier
            saved = api.request(f"inbounds/get/{identifier}")
            stream = object_value(saved.get("streamSettings"))
            if (
                saved.get("protocol") != "vless"
                or saved.get("port") != request["port"]
                or saved.get("listen") != bind
                or saved.get("remark") != request["remark"]
                or stream.get("network") != "xhttp"
                or stream.get("security") != "none"
                or (stream.get("xhttpSettings") or {}).get("path") != request["path"]
                or (stream.get("xhttpSettings") or {}).get("mode") != request["mode"]
            ):
                raise RuntimeError(message_text(MessageKey.DEPLOYMENT_API_FAILED))
            if before and identities(saved) != identities(before):
                # identities includes stream/network/settings: compare credentials
                # separately because changing XHTTP path is intentional.
                saved_clients = object_value(saved.get("settings")).get("clients", [])
                old_clients = object_value(before.get("settings")).get("clients", [])
                if saved_clients != old_clients:
                    raise RuntimeError(message_text(MessageKey.INBOUND_IDENTITIES))
            api.request("server/restartXrayService", {})
            updated = {
                "id": identifier,
                "domain": request["domain"],
                "path": request["path"],
                "mode": request["mode"],
                "port": request["port"],
                "listen": bind,
            }
            after_routes = [r for r in routes if r["id"] != identifier] + [updated]
            new_site = render_managed_site(
                self._subscriptions_only(previous_site.decode(), routes), after_routes
            )
            caddy.apply(base, new_site)
            for p, data in (
                (routes_path, json.dumps(after_routes, indent=2).encode()),
                (site_path, new_site.encode()),
            ):
                if (p.read_bytes() if p.exists() else None) != snapshot_files[p] or p.is_symlink():
                    raise RuntimeError(message_text(MessageKey.DEPLOYMENT_CADDY_CHANGED))
                private_write(p, data)
                written[p] = data
            fw.commit()
        except Exception:
            try:
                caddy.rollback()
            except Exception:
                self.context.emit(message_text(MessageKey.DEPLOYMENT_ROLLBACK_FAILED), "error")
            for p, data in written.items():
                if p.read_bytes() == data:
                    if snapshot_files[p] is None:
                        p.unlink()
                    else:
                        private_write(p, snapshot_files[p])
            if changed_id:
                try:
                    current = api.request(f"inbounds/get/{changed_id}")
                    if before is None:
                        # A newly created inbound is deleted only while it still
                        # has exactly the same owned configuration.
                        if (
                            current.get("remark") == request["remark"]
                            and current.get("port") == request["port"]
                            and object_value(current.get("settings"))
                            == object_value(proposed.get("settings"))
                        ):
                            api.request(f"inbounds/del/{changed_id}", {})
                    elif matches_update(current, proposed, before) or configuration(
                        current
                    ) == configuration(proposed):
                        api.request(f"inbounds/update/{changed_id}", before)
                        api.request("server/restartXrayService", {})
                except Exception:
                    self.context.emit(message_text(MessageKey.DEPLOYMENT_ROLLBACK_FAILED), "error")
            try:
                fw.rollback()
            except Exception:
                self.context.emit(message_text(MessageKey.DEPLOYMENT_ROLLBACK_FAILED), "error")
            raise
        self.context.emit(message_text(MessageKey.XHTTP_APPLIED, name=request["remark"]))

    @staticmethod
    def _subscriptions_only(previous_site, routes):
        """Remove only the exact snippets Nodekit saved previously."""
        for route in routes:
            snippet = site_for(route)
            if previous_site.count(snippet) != 1:
                raise RuntimeError(message_text(MessageKey.DEPLOYMENT_CADDY_CHANGED))
            previous_site = previous_site.replace("\n" + snippet, "", 1)
        return previous_site

    def publish_host(self, base, api, request):
        """Publish an existing XHTTP inbound in 3x-ui Hosts; never alter Caddy."""
        inbound = api.request(f"inbounds/get/{request['id']}")
        if (
            not isinstance(inbound, dict)
            or public_inbound(inbound)["fingerprint"] != request["expected_fingerprint"]
        ):
            raise RuntimeError(message_text(MessageKey.INBOUND_STALE))
        stream = object_value(inbound.get("streamSettings"))
        http = object_value(stream.get("xhttpSettings"))
        if (
            inbound.get("protocol") != "vless"
            or stream.get("network") != "xhttp"
            or stream.get("security") != "none"
            or http.get("path") != request["path"]
            or http.get("mode", "auto") != request["mode"]
            or inbound.get("port") != request["port"]
        ):
            raise RuntimeError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
        marker = f"nodekit:{self.context.node['id']}:host:{request['id']}"
        ledger = base / "xhttp-hosts.json"
        if ledger.is_symlink():
            raise RuntimeError(message_text(MessageKey.DEPLOYMENT_CADDY_CHANGED))
        original_ledger = ledger.read_bytes() if ledger.is_file() else None
        records = json.loads(original_ledger) if original_ledger else {}
        group_id = records.get(str(request["id"]))
        hosts = api.request("hosts/list") or []
        if not isinstance(hosts, list):
            raise RuntimeError(message_text(MessageKey.DEPLOYMENT_API_FAILED))
        owned = [h for h in hosts if h.get("remark") == marker]
        if len(owned) > 1 or (owned and not group_id):
            raise RuntimeError(message_text(MessageKey.DEPLOYMENT_CADDY_COLLISION))
        if group_id and (len(owned) != 1 or owned[0].get("groupId") != group_id):
            raise RuntimeError(message_text(MessageKey.DEPLOYMENT_CADDY_CHANGED))
        if any(
            h.get("groupId") != group_id
            and request["id"] in h.get("inboundIds", [])
            and (request["domain"] in h.get("hosts", []) or h.get("sni") == request["domain"])
            for h in hosts
        ):
            raise RuntimeError(message_text(MessageKey.DEPLOYMENT_CADDY_COLLISION))
        prior = copy.deepcopy(owned[0]) if owned else None
        payload = {
            "groupId": group_id or "",
            "inboundIds": [request["id"]],
            "hosts": [request["domain"]],
            "remark": marker,
            "port": 443,
            "security": "tls",
            "sni": request["domain"],
            "hostHeader": request["domain"],
            "path": request["path"],
            "alpn": ["h2"],
            "fingerprint": "chrome",
            "sortOrder": 0,
            "isDisabled": False,
            "isHidden": False,
            "allowInsecure": False,
            "randomCount": 1,
        }
        self.database.snapshot(self.inspector.database(), base / f"before-host-{time.time_ns()}.db")
        attempted = False
        try:
            attempted = True
            if group_id:
                api.request(f"hosts/update/{group_id}", payload)
            else:
                api.request("hosts/add", payload)
            after = [h for h in (api.request("hosts/list") or []) if h.get("remark") == marker]
            if len(after) != 1 or after[0].get("inboundIds") != [request["id"]]:
                raise RuntimeError(message_text(MessageKey.DEPLOYMENT_API_FAILED))
            record = after[0]
            if (
                record.get("hosts") not in ([request["domain"]], [request["domain"] + ":443"])
                or record.get("security") != "tls"
                or record.get("sni") != request["domain"]
            ):
                raise RuntimeError(message_text(MessageKey.DEPLOYMENT_API_FAILED))
            if not group_id:
                group_id = record["groupId"]
            if (
                ledger.is_symlink()
                or (ledger.read_bytes() if ledger.exists() else None) != original_ledger
            ):
                raise RuntimeError(message_text(MessageKey.DEPLOYMENT_CADDY_CHANGED))
            private_write(ledger, json.dumps({**records, str(request["id"]): group_id}).encode())
        except Exception:
            if attempted:
                try:
                    now = [
                        h for h in (api.request("hosts/list") or []) if h.get("remark") == marker
                    ]
                    if len(now) == 1 and now[0].get("inboundIds") == [request["id"]]:
                        if prior and group_id:
                            api.request(f"hosts/update/{group_id}", prior)
                        elif not prior:
                            api.request(f"hosts/del/{now[0]['groupId']}", {})
                except Exception:
                    self.context.emit(message_text(MessageKey.DEPLOYMENT_ROLLBACK_FAILED), "error")
            raise
        self.context.emit(message_text(MessageKey.XHTTP_APPLIED, name=request["remark"]))

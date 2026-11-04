"""Explicit API mutations with stale-state checks, identity preservation and scoped UFW."""

import copy
import json
import re
import secrets
import time
import uuid

from app.defaults import NODE_DEFAULTS
from framework.messages import MessageKey
from framework.messages import text as message_text

from .firewall import FirewallTransaction, desired_rules, protocols, reserved_caddy_ports, rule_spec
from .inbound_meta import object_value, public_inbound
from .native_release import NativeRelease
from .panel_api import PanelAPI


def managed_api(context, inspector, base):
    selected = inspector.selected
    try:
        manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))["node"]
        if (
            not selected
            or not selected["active"]
            or selected["installation"] != "managed"
            or context.node["panel"]["image"] != NODE_DEFAULTS.panel_image
            or manifest["id"] != context.node["id"]
            or base.is_symlink()
            or inspector.database().resolve() != (base / "db/x-ui.db").resolve()
            or int(selected["settings"]["webPort"]) != context.node["panel"]["port"]
            or selected["settings"]["webBasePath"] != context.node["panel"]["base_path"]
            or selected["settings"].get("webCertFile")
        ):
            raise ValueError()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(message_text(MessageKey.INBOUND_MANAGED_REQUIRED)) from exc
    token = base / "api-token"
    if token.is_file():
        return PanelAPI(context, token.read_text(encoding="utf-8").strip())
    command = (
        [
            "docker",
            "compose",
            "-f",
            str(base / "compose.yaml"),
            "run",
            "--rm",
            "--no-deps",
            "--entrypoint",
            "/app/x-ui",
            "panel",
        ]
        if selected.get("container")
        else NativeRelease(context).command(base)
    )
    return PanelAPI.from_cli(context, command, base)


def identities(value):
    stream = object_value(value.get("streamSettings"))
    reality = stream.get("realitySettings") or {}
    settings = object_value(value.get("settings"))
    if value.get("protocol") == "wireguard":
        settings = {k: v for k, v in settings.items() if k not in {"mtu", "dns"}}
    return {
        "settings": settings,
        "protocol": value.get("protocol"),
        "network": stream.get("network"),
        "security": stream.get("security"),
        "private_key": reality.get("privateKey"),
        "short_ids": reality.get("shortIds"),
        "public_key": (reality.get("settings") or {}).get("publicKey"),
    }


def configuration(value):
    return {
        k: (object_value(v) if k in {"settings", "streamSettings", "sniffing", "allocate"} else v)
        for k, v in value.items()
        if k not in {"clientStats", "up", "down"}
    }


def matches_update(saved, proposed, original):
    """3x-ui regenerates automatic tags and migrates routing when a port changes."""
    actual, expected = public_inbound(saved), public_inbound(proposed)
    actual_tag, expected_tag = actual.pop("tag"), expected.pop("tag")
    actual.pop("fingerprint")
    expected.pop("fingerprint")
    if actual != expected:
        return False
    if actual_tag == expected_tag:
        return True
    old_port, new_port = original["port"], proposed["port"]
    auto = re.fullmatch(rf"((?:n\d+-)?in-){old_port}-(tcp|udp|tcpudp|any)(?:-\d+)?", expected_tag)
    return bool(
        old_port != new_port
        and auto
        and re.fullmatch(rf"{re.escape(auto[1])}{new_port}-{auto[2]}(?:-\d+)?", actual_tag)
    )


class InboundManager:
    def __init__(self, context, host, database, inspector):
        self.context, self.host, self.database, self.inspector = context, host, database, inspector

    def apply(self, base):
        context = self.context
        change = context.payload["options"]["inbound"]
        api = managed_api(context, self.inspector, base)
        original = api.request(f"inbounds/get/{change['id']}")
        if (
            not isinstance(original, dict)
            or public_inbound(original)["fingerprint"] != change["expected_fingerprint"]
        ):
            raise RuntimeError(message_text(MessageKey.INBOUND_STALE))
        if change["operation"] == "update" and change.get("port") is not None:
            stream = object_value(original.get("streamSettings"))
            if stream.get("network") == "xhttp":
                # Port is also a Caddy upstream; update it transactionally through
                # the dedicated XHTTP workflow, never with this generic editor.
                raise RuntimeError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
        if change["operation"] == "delete":
            route_file = base / "xhttp-routes.json"
            if route_file.is_file():
                try:
                    routes = json.loads(route_file.read_text(encoding="utf-8"))
                    if any(r["id"] == change["id"] for r in routes):
                        raise RuntimeError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    raise RuntimeError(message_text(MessageKey.INBOUND_REQUEST_INVALID)) from exc
        if change["operation"] in {"add_client", "delete_client"}:
            self.apply_client(base, api, original, change)
            return
        if (
            any(change.get(k) is not None for k in ("wg_domain", "wg_mtu", "wg_dns"))
            and original.get("protocol") != "wireguard"
        ):
            raise RuntimeError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
        proposed = copy.deepcopy(original)
        if original.get("protocol") == "wireguard" and change.get("close_unmanaged_rule"):
            raise RuntimeError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
        old = public_inbound(original)
        if change["operation"] == "update":
            if change.get("wg_domain"):
                proposed.update(shareAddr=change["wg_domain"], shareAddrStrategy="custom")
            if change.get("wg_mtu") is not None or change.get("wg_dns") is not None:
                settings = object_value(proposed.get("settings"))
                if change.get("wg_mtu") is not None:
                    settings["mtu"] = change["wg_mtu"]
                if change.get("wg_dns") is not None:
                    import ipaddress

                    for address in filter(None, change["wg_dns"].split(",")):
                        ipaddress.ip_address(address.strip())
                    settings["dns"] = change["wg_dns"]
                proposed["settings"] = settings
            if change.get("remark") is not None:
                proposed["remark"] = change["remark"]
            if change.get("port") is not None:
                proposed["port"] = change["port"]
            if change.get("server_name"):
                stream = object_value(proposed.get("streamSettings"))
                if stream.get("security") != "reality":
                    raise RuntimeError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
                reality = stream["realitySettings"]
                field = "target" if "target" in reality else "dest"
                port = str(reality.get(field, "")).rsplit(":", 1)[-1]
                if not port.isdigit() or not 1 <= int(port) <= 65535:
                    raise RuntimeError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
                reality["serverNames"] = [change["server_name"]]
                reality[field] = f"{change['server_name']}:{port}"
                proposed["streamSettings"] = stream
            if proposed["port"] != original["port"]:
                reserved = {
                    context.node["panel"]["port"],
                    context.node["panel"]["subscription_port"],
                }
                reserved.update(reserved_caddy_ports(self.inspector.report))
                for proxy in self.inspector.report.get("caddy", []):
                    for publication in proxy.get("published_ports", []):
                        reserved.add(int(publication.rsplit("->", 1)[0].rsplit(":", 1)[1]))
                others = api.request("inbounds/list") or []
                if proposed["port"] in reserved or any(
                    i["id"] != original["id"] and i["port"] == proposed["port"] for i in others
                ):
                    raise RuntimeError(message_text(MessageKey.DEPLOYMENT_INBOUND_COLLISION))
                if original.get("protocol") == "wireguard":
                    if self.host.udp_port_bound(proposed["port"]):
                        raise RuntimeError(
                            message_text(MessageKey.PORT_OCCUPIED, port=proposed["port"])
                        )
                else:
                    self.host.require_endpoint(
                        proposed["port"], original.get("listen") or "0.0.0.0"
                    )
        self.database.snapshot(
            self.inspector.database(), base / f"before-inbound-{time.time_ns()}.db"
        )
        firewall = FirewallTransaction(
            context, base, enabled=(context.node.get("deployment") or {}).get("manage_ufw", True)
        )
        new = public_inbound(proposed)
        extra = (
            [rule_spec(new["port"], p) for p in protocols(new)]
            if change["operation"] == "update"
            and new["enabled"]
            and new["network"] != "xhttp"
            and new["listen"] not in {"127.0.0.1", "::1"}
            else []
        )
        attempted, deleted = False, False
        originals = {
            name: (base / name).read_bytes() if (base / name).is_file() else None
            for name in ("inbound-identities.json", "tunnel-connections.json", "subscriptions.json")
        }
        try:
            firewall.ensure(desired_rules(context, self.inspector.report, extra=extra))
            latest = api.request(f"inbounds/get/{change['id']}")
            if configuration(latest) != configuration(original):
                raise RuntimeError(message_text(MessageKey.INBOUND_STALE))
            attempted = True
            if change["operation"] == "delete":
                api.request(f"inbounds/del/{change['id']}", {})
                deleted = True
                if any(v["id"] == change["id"] for v in api.request("inbounds/list") or []):
                    raise RuntimeError(message_text(MessageKey.DEPLOYMENT_API_FAILED))
            else:
                api.request(f"inbounds/update/{change['id']}", proposed)
                saved = api.request(f"inbounds/get/{change['id']}")
                if not matches_update(saved, proposed, original) or identities(saved) != identities(
                    original
                ):
                    raise RuntimeError(message_text(MessageKey.INBOUND_IDENTITIES))
                new = public_inbound(saved)
                if new["enabled"]:
                    address = (
                        new["listen"] if new["listen"] not in {"0.0.0.0", "::"} else "127.0.0.1"
                    )
                    for _ in range(context.policy["readiness_attempts"]):
                        ready = (
                            self.host.udp_port_bound(new["port"])
                            if new["protocol"] == "wireguard"
                            else self.host.port_open(new["port"], address)
                        )
                        if ready:
                            break
                        time.sleep(context.policy["readiness_interval"])
                    else:
                        raise RuntimeError(message_text(MessageKey.INBOUND_IDENTITIES))
            self._remember(base, original, change, new)
            remaining = api.request("inbounds/list") or []
            used = {i["port"] for i in remaining if i.get("enable")}
            used.update(reserved_caddy_ports(self.inspector.report))
            for proxy in self.inspector.report.get("caddy", []):
                used.update(
                    int(p.rsplit("->", 1)[0].rsplit(":", 1)[1])
                    for p in proxy.get("published_ports", [])
                )
            if old["port"] not in used:
                for _ in range(min(context.policy["readiness_attempts"], 10)):
                    bound = (
                        self.host.udp_port_bound(old["port"])
                        if old["protocol"] == "wireguard"
                        else self.host.port_open(old["port"])
                    )
                    if not bound:
                        break
                    time.sleep(context.policy["readiness_interval"])
            firewall.prune(used, self.host)
            if change.get("close_unmanaged_rule") and old["port"] not in used:
                firewall.close_manual(old["port"], used, self.host)
            elif old["port"] not in used and any(
                not r["managed"] and r["port"] == str(old["port"])
                for r in firewall.finding["rules"]
            ):
                context.emit(
                    message_text(MessageKey.NETWORK_MANUAL_RULE, port=old["port"]), "warning"
                )
            firewall.commit()
            context.emit(
                message_text(
                    MessageKey.INBOUND_DELETED if deleted else MessageKey.INBOUND_UPDATED,
                    id=change["id"],
                )
            )
        except Exception:
            if attempted and not deleted:
                try:
                    saved = api.request(f"inbounds/get/{change['id']}")
                    if matches_update(saved, proposed, original):
                        api.request(f"inbounds/update/{change['id']}", original)
                        restored = api.request(f"inbounds/get/{change['id']}")
                        if public_inbound(restored)["fingerprint"] != old[
                            "fingerprint"
                        ] or identities(restored) != identities(original):
                            raise RuntimeError(message_text(MessageKey.INBOUND_IDENTITIES))
                    elif public_inbound(saved)["fingerprint"] != old["fingerprint"]:
                        context.emit(message_text(MessageKey.DEPLOYMENT_ROLLBACK_FAILED), "error")
                except Exception:
                    context.emit(message_text(MessageKey.DEPLOYMENT_ROLLBACK_FAILED), "error")
            if not deleted:
                try:
                    firewall.rollback()
                except Exception:
                    context.emit(message_text(MessageKey.DEPLOYMENT_ROLLBACK_FAILED), "error")
                for name, data in originals.items():
                    if data is None:
                        (base / name).unlink(missing_ok=True)
                    else:
                        (base / name).write_bytes(data)
            raise

    def _remember(self, base, original, change, updated):
        path = base / "inbound-identities.json"
        mapping = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        names = [name for name, record in mapping.items() if record["id"] == original["id"]]
        prefix = f"nodekit:{self.context.node['id']}:"
        if original.get("remark", "").startswith(prefix):
            names.append(original["remark"][len(prefix) :])
        for name in set(names):
            mapping[name] = {
                "id": original["id"],
                "deleted": change["operation"] == "delete",
                "edited": True,
            }
        path.write_text(json.dumps(mapping, indent=2), encoding="utf-8")
        path.chmod(0o600)
        for filename in ("tunnel-connections.json", "subscriptions.json"):
            output = base / filename
            if not output.exists():
                continue
            rows = json.loads(output.read_text(encoding="utf-8"))
            if change["operation"] == "delete":
                rows = [row for row in rows if row.get("name") not in names]
            else:
                for row in rows:
                    if row.get("name") not in names:
                        continue
                    row["remark"] = updated["remark"]
                    if filename == "tunnel-connections.json":
                        row["exit_port"] = updated["port"]
                        row["ssh_target"] = f"127.0.0.1:{updated['port']}"
                        if change.get("server_name"):
                            row["outbound"]["streamSettings"]["realitySettings"]["serverName"] = (
                                change["server_name"]
                            )
            output.write_text(json.dumps(rows, indent=2), encoding="utf-8")
            output.chmod(0o600)

    def apply_client(self, base, api, original, change):
        """Update one VLESS client without exporting its UUID or subscription ID."""
        if original.get("protocol") == "wireguard":
            from .wireguard import WireGuardManager

            return WireGuardManager(self.context, self.host, self.database, self.inspector).client(
                base, api, original, change
            )
        if original.get("protocol") != "vless":
            raise RuntimeError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
        proposed = copy.deepcopy(original)
        settings = object_value(proposed.get("settings"))
        clients = settings.get("clients")
        if not isinstance(clients, list) or any(not isinstance(c, dict) for c in clients):
            raise RuntimeError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
        email = change["client_email"]
        matches = [client for client in clients if client.get("email") == email]
        if (
            len(matches) > 1
            or (change["operation"] == "add_client" and matches)
            or (change["operation"] == "delete_client" and not matches)
        ):
            raise RuntimeError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
        if change["operation"] == "add_client":
            stream = object_value(proposed.get("streamSettings"))
            flow = (
                "xtls-rprx-vision"
                if stream.get("security") == "reality"
                and stream.get("network", "tcp") in {"tcp", "raw"}
                else ""
            )
            clients.append(
                {
                    "id": str(uuid.uuid4()),
                    "email": email,
                    "subId": secrets.token_urlsafe(18),
                    "flow": flow,
                    "enable": True,
                    "limitIp": 0,
                    "totalGB": 0,
                    "expiryTime": 0,
                }
            )
        else:
            settings["clients"] = [c for c in clients if c.get("email") != email]
        proposed["settings"] = settings

        # Compare the full private config locally. A public inventory fingerprint
        # intentionally does not contain client IDs and cannot detect this race.
        if configuration(api.request(f"inbounds/get/{change['id']}")) != configuration(original):
            raise RuntimeError(message_text(MessageKey.INBOUND_STALE))
        self.database.snapshot(
            self.inspector.database(), base / f"before-client-{time.time_ns()}.db"
        )
        attempted = False
        try:
            attempted = True
            api.request(f"inbounds/update/{change['id']}", proposed)
            saved = api.request(f"inbounds/get/{change['id']}")
            if configuration(saved) != configuration(proposed):
                raise RuntimeError(message_text(MessageKey.INBOUND_IDENTITIES))
            self.context.emit(message_text(MessageKey.INBOUND_UPDATED, id=change["id"]))
        except Exception:
            if attempted:
                try:
                    current = api.request(f"inbounds/get/{change['id']}")
                    if configuration(current) == configuration(proposed):
                        api.request(f"inbounds/update/{change['id']}", original)
                        if configuration(
                            api.request(f"inbounds/get/{change['id']}")
                        ) != configuration(original):
                            raise ValueError()
                    elif configuration(current) != configuration(original):
                        raise ValueError()
                except Exception:
                    self.context.emit(message_text(MessageKey.DEPLOYMENT_ROLLBACK_FAILED), "error")
            raise

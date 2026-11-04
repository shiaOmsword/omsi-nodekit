"""Scoped UFW transactions. Never enable/reset UFW or replace its ruleset."""

import ipaddress
import json
import re
import shutil
import socket

from framework.messages import MessageKey
from framework.messages import text as message_text

from .subscriptions import public_base


def parse_status(text):
    state = (
        "active"
        if re.search(r"^Status: active\s*$", text, re.M)
        else "inactive"
        if "Status: inactive" in text
        else "unknown"
    )
    rules = []
    for line in text.splitlines():
        match = re.match(
            r"^\[\s*(\d+)\]\s+(.+?)\s+(ALLOW|DENY|REJECT|LIMIT)\s+(IN|OUT|FWD)\s+(.+?)(?:\s+#\s*(.*))?$",
            line.strip(),
        )
        if not match:
            continue
        number, destination, action, direction, source, comment = match.groups()
        ipv6 = "(v6)" in destination or "(v6)" in source
        destination = destination.replace("(v6)", "").strip()
        source = source.replace("(v6)", "").strip()
        destination, _, interface = destination.partition(" on ")
        tokens = destination.split()
        address = "any"
        if tokens:
            try:
                address = str(ipaddress.ip_network(tokens[0], strict=False))
                tokens = tokens[1:]
            except ValueError:
                pass
        port, _, protocol = (tokens[0] if tokens else "any").partition("/")
        rules.append(
            {
                "number": int(number),
                "action": action,
                "direction": direction,
                "destination": address,
                "source": "any" if source == "Anywhere" else source,
                "port": port,
                "protocol": protocol or "any",
                "interface": interface or None,
                "ipv6": ipv6,
                "managed": bool(comment and comment.startswith("nodekit:")),
                "comment": comment if comment and comment.startswith("nodekit:") else None,
                "_comment": comment,
            }
        )
    return {"state": state, "rules": rules[:300], "warnings": []}


def public_firewall(finding):
    return {
        **finding,
        "rules": [
            {k: v for k, v in row.items() if not k.startswith("_")} for row in finding["rules"]
        ],
    }


def inspect_firewall(context):
    if not shutil.which("ufw"):
        return {"state": "unavailable", "rules": [], "warnings": []}
    try:
        result = context.runner.completed(
            ["env", "LC_ALL=C", "ufw", "status", "numbered"],
            timeout=context.policy["command_timeout"],
        )
        verbose = context.runner.completed(
            ["env", "LC_ALL=C", "ufw", "status", "verbose"],
            timeout=context.policy["command_timeout"],
        )
        if (
            result.returncode
            or verbose.returncode
            or len(result.stdout.encode()) > context.discovery["metadata_bytes"]
        ):
            raise ValueError()
        finding = parse_status(result.stdout)
        match = re.search(
            r"Default:\s*(\w+) \(incoming\),\s*(\w+) \(outgoing\),\s*(\w+) \(routed\)",
            verbose.stdout,
        )
        if match:
            finding.update(
                zip(("default_incoming", "default_outgoing", "default_routed"), match.groups())
            )
        return finding
    except (RuntimeError, OSError, ValueError):
        return {
            "state": "unknown",
            "rules": [],
            "warnings": [message_text(MessageKey.NETWORK_UFW_FAILED)],
        }


def protocols(inbound):
    if inbound.get("network") in {"kcp", "quic"} or inbound.get("protocol") in {
        "wireguard",
        "hysteria2",
    }:
        return ["udp"]
    return ["tcp", "udp"] if inbound.get("protocol") == "shadowsocks" else ["tcp"]


def rule_spec(
    port, protocol="tcp", *, source="any", destination="any", interface=None, scope="inbound"
):
    return {
        "port": int(port),
        "protocol": protocol,
        "source": source,
        "destination": destination,
        "interface": interface,
        "scope": scope,
    }


def rule_args(spec, comment):
    args = ["allow", "in"]
    if spec.get("interface"):
        args += ["on", spec["interface"]]
    return args + [
        "proto",
        spec["protocol"],
        "from",
        spec["source"],
        "to",
        spec["destination"],
        "port",
        str(spec["port"]),
        "comment",
        comment,
    ]


def _network_covers(rule_address, desired):
    if rule_address in {"any", "Anywhere"}:
        return True
    if desired == "any":
        return False
    try:
        return ipaddress.ip_network(desired, strict=False).subnet_of(
            ipaddress.ip_network(rule_address, strict=False)
        )
    except (ValueError, TypeError):
        return False


def matches(rule, spec):
    if (
        rule.get("ipv6")
        or rule["direction"] != "IN"
        or rule["protocol"] not in {"any", spec["protocol"]}
    ):
        return False
    if rule.get("interface") not in {None, spec.get("interface")}:
        return False
    if not _network_covers(rule["source"], spec["source"]) or not _network_covers(
        rule["destination"], spec["destination"]
    ):
        return False
    for part in rule["port"].split(","):
        try:
            start, _, end = part.partition(":")
            if int(start) <= spec["port"] <= int(end or start):
                return True
        except ValueError:
            if part in {"any", "Anywhere"}:
                return True
    return False


def permitted(finding, spec):
    if finding["state"] != "active":
        return None
    for rule in finding["rules"]:
        if matches(rule, spec):
            return rule["action"] in {"ALLOW", "LIMIT"}
    return finding.get("default_incoming") == "allow"


def desired_rules(context, report, *, extra=()):
    desired = list(extra)
    for panel in report.get("panels", []):
        if panel["id"] != report.get("selected_panel"):
            continue
        for inbound in panel.get("inbounds", []):
            if (
                inbound["enabled"]
                and inbound["network"] != "xhttp"
                and inbound["listen"] not in {"127.0.0.1", "::1", "localhost"}
            ):
                desired += [rule_spec(inbound["port"], p) for p in protocols(inbound)]
    target = context.node.get("deployment") or {}
    mapping = context.directory() / "inbound-identities.json"
    try:
        registered = json.loads(mapping.read_text(encoding="utf-8")) if mapping.is_file() else {}
    except (OSError, ValueError):
        registered = {}
    for inbound in target.get("inbounds", []):
        if inbound["name"] in registered:
            continue
        if inbound["listen"] == "0.0.0.0":
            desired.append(rule_spec(inbound["port"]))
    # XHTTP backends receive scoped bridge rules only. They must never become
    # public UFW allows merely because they bind a private non-loopback IP.
    path = context.directory() / "xhttp-routes.json"
    if path.is_file():
        try:
            routes = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            routes = []
        for route in routes:
            if route.get("listen") == "127.0.0.1":
                continue
            target = context.node.get("deployment") or {}
            proxies = [
                p for p in report.get("caddy", []) if caddy_matches(p, target.get("caddy_id"))
            ]
            bridges = [
                n
                for p in proxies
                for n in p.get("bridge_networks", [])
                if n.get("gateway") == route.get("listen")
            ]
            if len(bridges) == 1:
                bridge = bridges[0]
                desired.append(
                    rule_spec(
                        route["port"],
                        source=bridge["subnet"],
                        destination=route["listen"],
                        interface=bridge["interface"],
                        scope="xhttp",
                    )
                )
    if context.node["caddy"]["enabled"]:
        desired += [rule_spec(p, scope="caddy") for p in {80, context.node["caddy"]["https_port"]}]
        bind = target.get("subscription_bind", "127.0.0.1")
        if bind != "127.0.0.1":
            proxies = [
                p for p in report.get("caddy", []) if caddy_matches(p, target.get("caddy_id"))
            ]
            bridges = [
                n for p in proxies for n in p.get("bridge_networks", []) if n["gateway"] == bind
            ]
            if len(bridges) == 1:
                bridge = bridges[0]
                desired.append(
                    rule_spec(
                        context.node["panel"]["subscription_port"],
                        source=bridge["subnet"],
                        destination=bind,
                        interface=bridge["interface"],
                        scope="subscription",
                    )
                )
    return list({json.dumps(r, sort_keys=True): r for r in desired}.values())


def caddy_matches(proxy, selector):
    return proxy["id"] == selector or (
        proxy["installation"] == "docker"
        and proxy.get("container")
        and selector == "docker:" + proxy["container"]
    )


def reserved_caddy_ports(report):
    ports = set()
    for proxy in report.get("caddy", []):
        if not proxy.get("active"):
            continue
        values = [p.rsplit("->", 1)[0] for p in proxy.get("published_ports", [])]
        values += [v for r in proxy.get("routes", []) for v in r.get("listen", [])]
        for value in values:
            try:
                ports.add(int(value.rsplit(":", 1)[1]))
            except (ValueError, IndexError):
                pass
    return ports


def network_checks(context, report):
    finding = report.get("firewall") or {"state": "unknown", "rules": []}
    checks = []
    target = context.node.get("deployment") or {}
    for panel in report.get("panels", []):
        if panel["id"] != report.get("selected_panel"):
            continue
        for inbound in panel.get("inbounds", []):
            if inbound.get("protocol") == "wireguard":
                domain = inbound.get("wg_domain")
                try:
                    if not domain:
                        raise ValueError()
                    addresses = {
                        r[4][0]
                        for r in socket.getaddrinfo(
                            domain, inbound["port"], socket.AF_INET, socket.SOCK_DGRAM
                        )
                    }
                    expected = {
                        r[4][0]
                        for r in socket.getaddrinfo(
                            context.node["ssh"]["host"], None, socket.AF_INET
                        )
                    }
                    valid = bool(addresses & expected)
                    detail = f"WG endpoint {domain}: A {', '.join(sorted(addresses))}; " + (
                        "соответствует SSH-адресу VPS."
                        if valid
                        else "отличается от SSH-адреса VPS; проверь DNS."
                    )
                except (OSError, ValueError):
                    valid, detail = False, "WG endpoint: DNS не разрешён; проверь A-запись домена."
                checks.append(
                    {
                        "name": "wireguard_dns",
                        "state": "ok" if valid else "warning",
                        "detail": detail,
                    }
                )
            if inbound.get("security") == "reality" and (
                not inbound.get("server_names") or not inbound.get("target")
            ):
                checks.append(
                    {
                        "name": "inbound_config",
                        "state": "warning",
                        "detail": f"Inbound #{inbound['id']}: не заполнены REALITY serverNames или target.",
                    }
                )
        if context.node["caddy"]["enabled"]:
            actual = panel.get("settings") or {}
            expected = {
                "subPort": str(context.node["panel"]["subscription_port"]),
                "subListen": target.get("subscription_bind", "127.0.0.1"),
                "subURI": public_base(context.node),
                "subEnable": "true",
            }
            for key, value in expected.items():
                valid = actual.get(key) == value
                checks.append(
                    {
                        "name": "subscription_config",
                        "state": "ok" if valid else "warning",
                        "detail": f"{key}: соответствует конфигурации ноды."
                        if valid
                        else f"{key}: не заполнен или отличается от конфигурации ноды. Ожидается {value}.",
                    }
                )
    for spec in desired_rules(context, report):
        allowed = permitted(finding, spec)
        detail = f"{spec['port']}/{spec['protocol']} · {spec['scope']}"
        if spec.get("interface"):
            detail += f" · {spec['interface']} · {spec['source']} → {spec['destination']}"
        checks.append(
            {
                "name": "ufw",
                "state": "ok" if allowed else "warning",
                "detail": detail
                + (
                    ": разрешение UFW найдено."
                    if allowed
                    else ": UFW не активен/не прочитан."
                    if allowed is None
                    else ": разрешение UFW не найдено или перекрыто запретом."
                ),
            }
        )
    for proxy in report.get("caddy", []):
        if not caddy_matches(proxy, (context.node.get("deployment") or {}).get("caddy_id")):
            continue
        if proxy["installation"] == "docker" and proxy.get("network_mode") != "host":
            for port in {80, context.node["caddy"]["https_port"]}:
                present = any(
                    p.endswith(f":{port}->{port}/tcp") for p in proxy.get("published_ports", [])
                )
                checks.append(
                    {
                        "name": "caddy_port",
                        "state": "ok" if present else "warning",
                        "detail": f"Caddy {port}:{port}/tcp: "
                        + (
                            "опубликован."
                            if present
                            else "не опубликован; требуется согласование Compose."
                        ),
                    }
                )
    return checks


class FirewallTransaction:
    def __init__(self, context, base, *, enabled=True):
        self.context, self.base, self.enabled = context, base, enabled
        self.finding = inspect_firewall(context)
        self.added, self.removed = [], []
        path = base / "firewall-rules.json"
        self.original_ledger = path.read_bytes() if path.is_file() else None
        self.ledger_written = False
        self.owned = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []

    def _run(self, args):
        self.context.runner.run(
            ["env", "LC_ALL=C", "ufw", *args],
            timeout=self.context.policy["command_timeout"],
            sensitive=True,
        )
        self.finding = inspect_firewall(self.context)
        if self.finding["state"] != "active":
            raise RuntimeError(message_text(MessageKey.NETWORK_UFW_FAILED))

    def ensure(self, desired):
        if not self.enabled or self.finding["state"] in {"inactive", "unavailable"}:
            return
        if self.finding["state"] != "active":
            raise RuntimeError(message_text(MessageKey.NETWORK_UFW_FAILED))
        for spec in desired:
            if permitted(self.finding, spec):
                continue
            if any(
                r["action"] in {"DENY", "REJECT"} and matches(r, spec)
                for r in self.finding["rules"]
            ):
                raise RuntimeError(message_text(MessageKey.NETWORK_UFW_FAILED))
            comment = f"nodekit:{self.context.node['id']}:{spec['scope']}:{spec['port']}:{spec['protocol']}"
            args = rule_args(spec, comment)
            entry = {**spec, "comment": comment}
            self.added.append(entry)
            self._run(args)
            if not permitted(self.finding, spec) or not any(
                r.get("comment") == comment for r in self.finding["rules"]
            ):
                raise RuntimeError(message_text(MessageKey.NETWORK_UFW_FAILED))
            self.context.emit(
                message_text(
                    MessageKey.NETWORK_RULE_ADDED,
                    port=spec["port"],
                    protocol=spec["protocol"],
                    scope=spec["scope"],
                )
            )

    def prune(self, used_ports, host):
        if not self.enabled or self.finding["state"] != "active":
            return
        for entry in self.owned + self.added:
            if (
                entry["scope"] not in {"inbound", "xhttp"}
                or entry["port"] in used_ports
                or host.port_open(entry["port"])
                or (entry["protocol"] == "udp" and host.udp_port_bound(entry["port"]))
            ):
                continue
            if not any(
                r.get("comment") == entry["comment"] and matches(r, entry)
                for r in self.finding["rules"]
            ):
                continue
            self._run(["--force", "delete", *rule_args(entry, entry["comment"])])
            self.removed.append(entry)
            self.context.emit(
                message_text(
                    MessageKey.NETWORK_RULE_REMOVED, port=entry["port"], protocol=entry["protocol"]
                )
            )

    def close_manual(self, port, used_ports, host):
        if (
            not self.enabled
            or self.finding["state"] != "active"
            or port in used_ports
            or host.port_open(port)
        ):
            return
        candidates = [
            r
            for r in self.finding["rules"]
            if not r["managed"]
            and not r["ipv6"]
            and r["action"] == "ALLOW"
            and r["direction"] == "IN"
            and r["port"] == str(port)
            and r["protocol"] == "tcp"
            and r["destination"] == "any"
            and r["source"] == "any"
            and not r["interface"]
        ]
        for rule in candidates:
            # Exact port-only rule; never delete broad ranges/profiles/subnets or a numbered rule.
            protocol = "/tcp" if rule["protocol"] == "tcp" else ""
            self._run(["--force", "delete", "allow", str(port) + protocol])
            self.removed.append(
                {
                    "manual": True,
                    "port": port,
                    "protocol": rule["protocol"],
                    "comment": rule.get("_comment"),
                    "position": rule["number"],
                }
            )

    def commit(self):
        if not self.enabled or self.finding["state"] != "active":
            return
        entries = [e for e in self.owned + self.added if e not in self.removed]
        self.base.mkdir(parents=True, exist_ok=True, mode=0o700)
        output = self.base / "firewall-rules.json"
        if (output.read_bytes() if output.exists() else None) != self.original_ledger:
            raise RuntimeError(message_text(MessageKey.NETWORK_UFW_FAILED))
        temporary = self.base / "firewall-rules.json.tmp"
        temporary.write_text(json.dumps(entries, indent=2), encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(output)
        self.ledger_written = True

    def rollback(self):
        for entry in reversed(self.added):
            if entry not in self.removed:
                self._run(["--force", "delete", *rule_args(entry, entry["comment"])])
        for entry in self.removed:
            if entry in self.added:
                continue
            if entry.get("manual"):
                suffix = "/tcp" if entry["protocol"] == "tcp" else ""
                self._run(
                    [
                        "insert",
                        str(min(entry["position"], len(self.finding["rules"]) + 1)),
                        "allow",
                        str(entry["port"]) + suffix,
                    ]
                    + (["comment", entry["comment"]] if entry.get("comment") else [])
                )
            else:
                self._run(rule_args(entry, entry["comment"]))
        if self.ledger_written:
            output = self.base / "firewall-rules.json"
            if self.original_ledger is None:
                output.unlink(missing_ok=True)
            else:
                output.write_bytes(self.original_ledger)

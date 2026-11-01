"""Transactional pool of independent OpenSSH TCP sessions into one Xray balancer."""

import copy
import json
import time

from framework.messages import MessageKey
from framework.messages import text as message_text

from .inbound_manager import managed_api
from .inbound_meta import public_inbound
from .tunnel_errors import TunnelPreflightError
from .tunnel_forward import TunnelForward
from .tunnel_manager import TunnelManager, loopback_outbound, private_write, routed_template


def pool_template(
    original, source_tag, node_id, pool_name, tunnels, inbound_tag, previous=None, singles=None
):
    """Return a copy, private ownership record. Never mutate shared Xray objects."""
    config = copy.deepcopy(original)
    prefix = f"ssh-{node_id}-pool-{pool_name}-"
    balancer_tag = f"ssh-{node_id}-balancer-{pool_name}"
    if not any(
        o.get("tag") == "blocked" and o.get("protocol") == "blackhole"
        for o in config.get("outbounds", [])
    ):
        raise TunnelPreflightError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))
    if len(tunnels) < 2 or len({t["local_port"] for t in tunnels}) != len(tunnels):
        raise TunnelPreflightError(message_text(MessageKey.TUNNEL_CONFIG_INVALID))
    # Reuse the exact validated VLESS schemas and chain-rejection logic.
    routed_template(config, source_tag, tunnels[0], prefix + "_validation", inbound_tag)
    source = next(o for o in config["outbounds"] if o.get("tag") == source_tag)
    pool_tags = [prefix + tunnel["name"] for tunnel in tunnels]
    clones = [
        loopback_outbound(source, tag, tunnel["local_port"])
        for tag, tunnel in zip(pool_tags, tunnels)
    ]
    singles = singles or []
    if previous and singles:
        raise TunnelPreflightError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))
    if previous:
        if previous.get("source_tag") != source_tag or previous.get("inbound_tag") != inbound_tag:
            raise TunnelPreflightError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))
        for saved in previous["outbounds"]:
            if config["outbounds"].count(saved) != 1:
                raise TunnelPreflightError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))
            config["outbounds"].remove(saved)
        if original.get("observatory") != previous.get("observatory"):
            raise TunnelPreflightError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))
        routing = config.setdefault("routing", {})
        if routing.get("balancers", []).count(previous["balancer"]) != 1:
            raise TunnelPreflightError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))
        old_balancer_index = routing["balancers"].index(previous["balancer"])
        routing["balancers"].remove(previous["balancer"])
        if routing.setdefault("rules", []).count(previous["rule"]) != 1:
            raise TunnelPreflightError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))
        rule_index = routing["rules"].index(previous["rule"])
        routing["rules"].remove(previous["rule"])
    else:
        routing = config.setdefault("routing", {})
        old_balancer_index = len(routing.setdefault("balancers", []))
        rule_index = 0
        if singles:
            # A node can already have several individually installed, owned SSH
            # outbounds for the same inbound. Replace all of them atomically,
            # never just the first route or the first systemd service.
            rules = routing.setdefault("rules", [])
            source_by_name = {t["name"]: t for t in tunnels}
            old_indices = []
            old_tags = set()
            if len({row["name"] for row in singles}) != len(singles):
                raise TunnelPreflightError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))
            for saved in singles:
                name = saved["name"]
                tunnel = source_by_name.get(name)
                tag = f"ssh-{node_id}-{name}"
                if tunnel is None or tag in old_tags:
                    raise TunnelPreflightError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))
                # Ensure existing credentials, transport, local TCP port and
                # owner tag all match the selected original VLESS outbound.
                expected = loopback_outbound(source, tag, tunnel["local_port"])
                if (
                    saved.get("outbound") != expected
                    or saved.get("rule")
                    != {
                        "type": "field",
                        "inboundTag": [inbound_tag],
                        "outboundTag": tag,
                    }
                    or config["outbounds"].count(expected) != 1
                    or rules.count(saved["rule"]) != 1
                ):
                    raise TunnelPreflightError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))
                old_indices.append(rules.index(saved["rule"]))
                old_tags.add(tag)
            # Another rule or balancer referencing an old single tag may not
            # be owned by this pool; replacing it could break a third-party route.
            owned_rules = [row["rule"] for row in singles]
            if any(r.get("outboundTag") in old_tags for r in rules if r not in owned_rules) or any(
                any(
                    t == selector or t.startswith(selector)
                    for selector in b.get("selector", [])
                    for t in old_tags
                )
                for b in routing.get("balancers", [])
            ):
                raise TunnelPreflightError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))
            rule_index = min(old_indices)
            for saved in singles:
                config["outbounds"].remove(saved["outbound"])
                rules.remove(saved["rule"])
            # Removing earlier owned rules shifts the insertion index.
            rule_index -= sum(i < rule_index for i in old_indices)
        else:
            protected = {"blocked"}
            if (config.get("api") or {}).get("tag"):
                protected.add(config["api"]["tag"])
            rules = routing.setdefault("rules", [])
            while rule_index < len(rules) and rules[rule_index].get("outboundTag") in protected:
                rule_index += 1
    if any(o.get("tag", "").startswith(prefix) for o in config["outbounds"]):
        raise TunnelPreflightError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))
    if any(b.get("tag") == balancer_tag for b in routing.get("balancers", [])):
        raise TunnelPreflightError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))
    # The fallback must be blackhole, never "direct". No egress leak if all links fail.
    balancer = {
        "tag": balancer_tag,
        "selector": [prefix],
        "fallbackTag": "blocked",
        "strategy": {"type": "roundRobin", "settings": {}},
    }
    rule = {"type": "field", "inboundTag": [inbound_tag], "balancerTag": balancer_tag}
    if any(r.get("balancerTag") == balancer_tag for r in routing["rules"]):
        raise TunnelPreflightError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))
    config["outbounds"].extend(clones)
    routing["balancers"].insert(old_balancer_index, balancer)
    routing["rules"].insert(rule_index, rule)
    if previous:
        # The observer is owned by this pool only at the selector level; operator
        # config changes after the last apply must be rejected.
        observer = copy.deepcopy(config["observatory"])
    else:
        observer = copy.deepcopy(config.get("observatory"))
        if observer is None:
            observer = {
                "subjectSelector": [prefix],
                "probeUrl": "https://www.google.com/generate_204",
                "probeInterval": "15s",
                "enableConcurrency": True,
            }
        else:
            selectors = observer.get("subjectSelector")
            if not isinstance(selectors, list) or not all(isinstance(x, str) for x in selectors):
                raise TunnelPreflightError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))
            if prefix not in selectors:
                selectors.append(prefix)
    config["observatory"] = observer
    record = {
        "source_tag": source_tag,
        "inbound_tag": inbound_tag,
        "members": [t["name"] for t in tunnels],
        "outbounds": clones,
        "balancer": balancer,
        "rule": rule,
        "observatory": observer,
    }
    return config, record


class TunnelPoolManager:
    def __init__(self, context, host, database, inspector):
        self.context, self.host, self.database, self.inspector = context, host, database, inspector

    def apply(self, base):
        context = self.context
        request = context.payload["options"]["tunnel"]
        stage = "pool preflight"
        api = managed_api(context, self.inspector, base)
        all_tunnels = {t["name"]: t for t in context.node["tunnels"]}
        names = request["members"]
        if len(names) != len(set(names)) or names[0] != request["name"] or len(names) < 2:
            raise RuntimeError(message_text(MessageKey.TUNNEL_CONFIG_INVALID))
        try:
            tunnels = [all_tunnels[name] for name in names]
        except KeyError as exc:
            raise RuntimeError(message_text(MessageKey.TUNNEL_CONFIG_INVALID)) from exc
        if len({(t["host"], t["target_port"]) for t in tunnels}) != 1:
            raise RuntimeError(message_text(MessageKey.TUNNEL_CONFIG_INVALID))
        if not all_tunnels or not request.get("pool_name"):
            raise RuntimeError(message_text(MessageKey.TUNNEL_CONFIG_INVALID))
        pool_name = request["pool_name"]
        pool_path = base / f"pool-{pool_name}.json"
        manifest_path = base / "manifest.json"
        if any(p.is_symlink() for p in (pool_path, manifest_path)):
            raise RuntimeError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))
        originals = {p: p.read_bytes() if p.is_file() else None for p in (pool_path, manifest_path)}
        previous = json.loads(originals[pool_path]) if originals[pool_path] else None
        if previous and (
            previous.get("inbound_id") != request["id"]
            or previous.get("source_tag") != request["outbound_tag"]
            or previous.get("members") != names
        ):
            # Changing pool membership would also need an explicit operation
            # to retire unused systemd units. Do not leak orphan SSH sessions.
            raise RuntimeError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))

        # Discover all owned single routes for this inbound. Previously only
        # tunnel-<first-member>.json was considered, even when another selected
        # member already had a valid Nodekit-managed route.
        single_records = []
        for path in base.glob("tunnel-*.json"):
            if path.is_symlink() or not path.is_file():
                raise RuntimeError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))
            name = path.name[len("tunnel-") : -len(".json")]
            state_bytes = path.read_bytes()
            state = json.loads(state_bytes)
            if name in names or state.get("inbound_id") == request["id"]:
                originals[path] = state_bytes
                if state.get("pooled_into") == pool_name and previous:
                    if state.get("inbound_id") != request["id"] or name not in names:
                        raise RuntimeError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))
                    continue
                if (
                    name not in names
                    or state.get("inbound_id") != request["id"]
                    or state.get("pooled_into")
                    or previous
                ):
                    raise RuntimeError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))
                single_records.append({"name": name, **state})
        for path in base.glob("pool-*.json"):
            if path == pool_path:
                continue
            if path.is_symlink():
                raise RuntimeError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))
            state = json.loads(path.read_text(encoding="utf-8"))
            if state.get("inbound_id") == request["id"]:
                raise RuntimeError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))
        if previous:
            migrated = previous.get("migrated_names", [])
            if any(
                (base / f"tunnel-{name}.json") not in originals
                or json.loads(originals[base / f"tunnel-{name}.json"]).get("pooled_into")
                != pool_name
                for name in migrated
            ):
                raise RuntimeError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))
        forwards, attempted = [], False
        original = proposed = None
        written = {}
        manager = TunnelManager(context, self.host, self.database, self.inspector)
        try:
            stage = "inbound freshness"
            inbound = public_inbound(api.request(f"inbounds/get/{request['id']}"))
            if (
                not inbound["enabled"]
                or not inbound["tag"]
                or inbound["fingerprint"] != request["expected_fingerprint"]
            ):
                raise TunnelPreflightError(message_text(MessageKey.INBOUND_STALE))
            stage = "Xray pool ownership"
            original = manager.template(api)
            proposed, record = pool_template(
                original,
                request["outbound_tag"],
                context.node["id"],
                pool_name,
                tunnels,
                inbound["tag"],
                previous,
                single_records,
            )
            if previous and previous.get("members") == names and proposed == original:
                # Idempotent, but still verify live transport before reporting success.
                pass
            stage = "SSH units and identities"
            for tunnel in tunnels:
                forward = TunnelForward(context, self.host, tunnel)
                forward.preflight()
                forwards.append(forward)
            stage = "private recovery snapshots"
            stamp = time.time_ns()
            self.database.snapshot(self.inspector.database(), base / f"before-pool-{stamp}.db")
            recovery = base / f"before-pool-{stamp}.json"
            recovery.write_text(json.dumps(original), encoding="utf-8")
            recovery.chmod(0o600)
            stage = "start independent SSH sessions"
            for forward in forwards:
                forward.start()
                manager.wait(forward.ready)
            stage = "HTTPS probe each SSH exit"
            for outbound in record["outbounds"]:
                manager.probe(outbound)
            stage = "concurrent change check"
            if (
                manager.template(api) != original
                or public_inbound(api.request(f"inbounds/get/{request['id']}"))["fingerprint"]
                != request["expected_fingerprint"]
            ):
                raise TunnelPreflightError(message_text(MessageKey.INBOUND_STALE))
            stage = "apply Xray round-robin pool"
            attempted = True
            api.request("xray/update", {"xraySetting": json.dumps(proposed)}, form=True)
            if manager.template(api) != proposed:
                raise ValueError()
            api.request("server/restartXrayService", {})
            stage = "runtime and egress verification"

            def active():
                try:
                    path, _ = __import__(
                        "app.agent.egress", fromlist=["runtime_paths"]
                    ).runtime_paths(context, self.inspector)
                    live = json.loads(path.read_text(encoding="utf-8"))
                    return (
                        all(o in live["outbounds"] for o in record["outbounds"])
                        and record["rule"] in live["routing"]["rules"]
                        and record["balancer"] in live["routing"]["balancers"]
                    )
                except (OSError, ValueError, TypeError, KeyError, AttributeError):
                    return False

            manager.wait(active)
            for outbound in record["outbounds"]:
                manager.probe(outbound)
            stage = "write owned pool metadata"
            manifest = json.loads(originals[manifest_path])
            applied = {t["name"]: t for t in manifest["node"]["tunnels"]}
            for tunnel in tunnels:
                applied[tunnel["name"]] = tunnel
            manifest["node"]["tunnels"] = list(applied.values())
            record.update(inbound_id=request["id"], pool_name=pool_name)
            record["migrated_names"] = (
                previous.get("migrated_names", [])
                if previous
                else [row["name"] for row in single_records]
            )
            changes = {pool_path: record, manifest_path: manifest}
            for row in single_records:
                path = base / f"tunnel-{row['name']}.json"
                state = {k: v for k, v in row.items() if k != "name"}
                changes[path] = {**state, "pooled_into": pool_name}
            for path, value in changes.items():
                if (
                    path.is_symlink()
                    or (path.read_bytes() if path.exists() else None) != originals[path]
                ):
                    raise TunnelPreflightError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))
                data = json.dumps(value, indent=2).encode("utf-8")
                private_write(path, data)
                written[path] = data
        except Exception as exc:
            if isinstance(exc, TunnelPreflightError):
                context.emit(str(exc), "error")
            else:
                context.emit(
                    message_text(MessageKey.TUNNEL_ERROR_TYPE, kind=type(exc).__name__), "error"
                )
            safe_to_stop = True
            if attempted:
                try:
                    current = manager.template(api)
                    if current == proposed:
                        api.request("xray/update", {"xraySetting": json.dumps(original)}, form=True)
                        api.request("server/restartXrayService", {})
                        if manager.template(api) != original:
                            raise ValueError()
                    elif current != original:
                        raise ValueError()
                except Exception:
                    safe_to_stop = False
                    context.emit(message_text(MessageKey.DEPLOYMENT_ROLLBACK_FAILED), "error")
            for path, data in written.items():
                try:
                    if path.read_bytes() != data or path.is_symlink():
                        raise ValueError()
                    if originals[path] is None:
                        path.unlink()
                    else:
                        private_write(path, originals[path])
                except Exception:
                    context.emit(message_text(MessageKey.DEPLOYMENT_ROLLBACK_FAILED), "error")
            if safe_to_stop:
                for forward in reversed(forwards):
                    try:
                        forward.rollback()
                    except Exception:
                        context.emit(message_text(MessageKey.DEPLOYMENT_ROLLBACK_FAILED), "error")
            raise RuntimeError(message_text(MessageKey.TUNNEL_APPLY_FAILED, stage=stage)) from exc
        context.emit(
            message_text(MessageKey.TUNNEL_APPLIED, name=pool_name, tag=record["balancer"]["tag"])
        )

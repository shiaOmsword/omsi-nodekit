import copy
import hashlib
import json
import re

from framework.messages import MessageKey
from framework.messages import text as message_text

from .egress import runtime_paths
from .tunnel_errors import TunnelPreflightError


def route_ids(record):
    ids = record.get("inbound_ids", [record.get("inbound_id")])
    tags = record["rule"].get("inboundTag")
    if (
        not isinstance(ids, list)
        or not 1 <= len(ids) <= 100
        or any(type(i) is not int or i <= 0 for i in ids)
        or len(set(ids)) != len(ids)
        or record.get("inbound_id") != ids[0]
        or not isinstance(tags, list)
        or len(tags) != len(ids)
        or any(not isinstance(t, str) or not t for t in tags)
        or len(set(tags)) != len(tags)
    ):
        raise TunnelPreflightError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))
    return ids


def refresh_route(record, inbounds):
    result = copy.deepcopy(record)
    by_id = {i["id"]: i for i in inbounds}
    result["rule"]["inboundTag"] = [
        by_id.get(identifier, {}).get("tag") or tag
        for identifier, tag in zip(route_ids(record), record["rule"]["inboundTag"])
    ]
    if "balancer" in result:
        result["inbound_tag"] = result["rule"]["inboundTag"][0]
    return result


def verify_route(config, record):
    key = "balancerTag" if "balancer" in record else "outboundTag"
    tag = record["balancer" if "balancer" in record else "outbound"]["tag"]
    rule = record["rule"]
    rules = (config.get("routing") or {}).get("rules", [])
    if rule != {"type": "field", "inboundTag": rule["inboundTag"], key: tag} or (
        rules.count(rule) != 1 or any(r.get(key) == tag for r in rules if r != rule)
    ):
        raise TunnelPreflightError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))


def verify_exit(config, record, *, runtime=False):
    route_ids(record)
    verify_route(config, record)
    outbounds = record["outbounds"] if "balancer" in record else [record["outbound"]]
    if any(config.get("outbounds", []).count(o) != 1 for o in outbounds):
        raise TunnelPreflightError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))
    if "balancer" in record and (
        (config.get("routing") or {}).get("balancers", []).count(record["balancer"]) != 1
        or (not runtime and config.get("observatory") != record["observatory"])
    ):
        raise TunnelPreflightError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))


def read_exit(context, kind, name):
    if kind not in {"tunnel", "pool"} or not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", name):
        raise TunnelPreflightError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))
    if context.directory().is_symlink():
        raise TunnelPreflightError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))
    path = context.directory() / f"{kind}-{name}.json"
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_size > context.discovery["metadata_bytes"]
    ):
        raise TunnelPreflightError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))
    raw = path.read_bytes()
    record = json.loads(raw)
    route_ids(record)
    names = record["members"] if kind == "pool" else [name]
    configured = {t["name"] for t in context.node["tunnels"]}
    prefix = f"ssh-{context.node['id']}-"
    if (
        not names
        or len(set(names)) != len(names)
        or not set(names) <= configured
        or record.get("pooled_into")
        or (kind == "tunnel" and record["outbound"]["tag"] != prefix + name)
        or (
            kind == "pool"
            and (
                record.get("pool_name") != name
                or len(names) < 2
                or record["balancer"]["tag"] != prefix + "balancer-" + name
                or [o["tag"] for o in record["outbounds"]]
                != [prefix + "pool-" + name + "-" + member for member in names]
            )
        )
    ):
        raise TunnelPreflightError(message_text(MessageKey.TUNNEL_ROUTE_OWNERSHIP))
    return path, raw, record, names


def exit_inventory(context, inspector):
    if not inspector.selected or inspector.selected["installation"] != "managed":
        return []
    try:
        path, _ = runtime_paths(context, inspector)
        if (
            not path
            or not path.is_file()
            or path.stat().st_size > context.discovery["metadata_bytes"]
        ):
            return []
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    candidates = [("tunnel", t["name"]) for t in context.node["tunnels"]]
    candidates += [
        ("pool", p.stem[5:]) for p in sorted(context.directory().glob("pool-*.json"))[:100]
    ]
    result = []
    for kind, name in candidates:
        if not (context.directory() / f"{kind}-{name}.json").exists():
            continue
        try:
            _, raw, record, members = read_exit(context, kind, name)
            record = refresh_route(record, inspector.selected.get("inbounds", []))
            verify_exit(config, record, runtime=True)
            result.append(
                {
                    "kind": kind,
                    "name": name,
                    "members": members,
                    "inbound_ids": route_ids(record),
                    "fingerprint": hashlib.sha256(raw).hexdigest(),
                }
            )
        except (OSError, ValueError, KeyError, TypeError, AttributeError, TunnelPreflightError):
            continue
    return result

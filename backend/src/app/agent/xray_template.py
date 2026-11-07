"""Public saved-template inventory and scoped Xray configuration builders."""

import copy
import hashlib
import json
import sqlite3
from contextlib import closing

from framework.messages import MessageKey
from framework.messages import text as message_text

from .tunnel_errors import TunnelPreflightError


def fingerprint(config):
    return hashlib.sha256(
        json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def editable_rule(rule, api_tag=None):
    return (
        isinstance(rule, dict)
        and set(rule) <= {"type", "inboundTag", "outboundTag", "balancerTag", "enabled", "comment"}
        and rule.get("type", "field") == "field"
        and rule.get("enabled", True) is True
        and isinstance(rule.get("inboundTag"), list)
        and bool(rule["inboundTag"])
        and all(isinstance(t, str) and t and t != api_tag for t in rule["inboundTag"])
        and bool(rule.get("outboundTag")) != bool(rule.get("balancerTag"))
        and (not api_tag or rule.get("outboundTag") != api_tag)
    )


def observer_config(config, selectors):
    observer = copy.deepcopy(config.get("observatory"))
    if observer is None:
        observer = {
            "subjectSelector": [],
            "probeUrl": "https://www.google.com/generate_204",
            "probeInterval": "15s",
            "enableConcurrency": True,
        }
    current = observer.get("subjectSelector")
    if not isinstance(current, list) or not all(isinstance(t, str) for t in current):
        raise TunnelPreflightError(message_text(MessageKey.XRAY_CONFIG_INVALID))
    observer["subjectSelector"] = list(dict.fromkeys([*current, *selectors]))
    return observer


def add_balancer(original, tag, members, fallback):
    config = copy.deepcopy(original)
    outbounds = config.get("outbounds", [])
    tags = [o.get("tag") for o in outbounds]
    if (
        not members
        or len(members) != len(set(members))
        or any(tags.count(t) != 1 for t in [*members, fallback])
        or fallback in members
        or tag in tags
        or (config.get("api") or {}).get("tag") == tag
    ):
        raise TunnelPreflightError(message_text(MessageKey.XRAY_CONFIG_INVALID))
    matched = {t for t in tags if isinstance(t, str) and any(t.startswith(s) for s in members)}
    if matched != set(members):
        raise TunnelPreflightError(message_text(MessageKey.XRAY_SELECTOR_CONFLICT))
    balancer = {
        "tag": tag,
        "selector": members,
        "fallbackTag": fallback,
        "strategy": {"type": "roundRobin"},
    }
    balancers = config.setdefault("routing", {}).setdefault("balancers", [])
    existing = [b for b in balancers if b.get("tag") == tag]
    if existing and existing != [balancer]:
        raise TunnelPreflightError(message_text(MessageKey.XRAY_CONFIG_INVALID))
    if not existing:
        balancers.append(balancer)
    if config.get("burstObservatory") is not None:
        observer = copy.deepcopy(config["burstObservatory"])
        selectors = observer.get("subjectSelector")
        if not isinstance(selectors, list) or not all(isinstance(t, str) for t in selectors):
            raise TunnelPreflightError(message_text(MessageKey.XRAY_CONFIG_INVALID))
        observer["subjectSelector"] = list(dict.fromkeys([*selectors, *members]))
        config["burstObservatory"] = observer
    else:
        config["observatory"] = observer_config(config, members)
    return config


def saved_routing_inventory(context, inspector):
    empty = {"readable": False, "outbounds": [], "balancers": [], "rules": []}
    if not inspector.selected or inspector.selected["installation"] != "managed":
        return empty
    try:
        path = inspector.database()
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            db.execute("PRAGMA query_only=ON")
            row = db.execute(
                "SELECT value FROM settings WHERE key=?", ("xrayTemplateConfig",)
            ).fetchone()
        if not row or len(row[0].encode()) > context.discovery["metadata_bytes"]:
            return empty
        config = json.loads(row[0])
        routing = config.get("routing") or {}
        outbounds = [
            {"tag": o.get("tag", ""), "protocol": o.get("protocol", "")}
            for o in config["outbounds"][:100]
        ]
        tags = [o.get("tag") for o in config["outbounds"] if isinstance(o.get("tag"), str)]
        balancers = [
            {
                "tag": b.get("tag", ""),
                "selector": b.get("selector", []),
                "members": [t for t in tags if any(t.startswith(s) for s in b.get("selector", []))],
                "strategy": (b.get("strategy") or {}).get("type", "random"),
                "fallback_tag": b.get("fallbackTag", ""),
            }
            for b in routing.get("balancers", [])[:100]
        ]
        rules = [
            {
                "index": i,
                "inbound_tags": r.get("inboundTag", []),
                "outbound_tag": r.get("outboundTag", ""),
                "balancer_tag": r.get("balancerTag", ""),
                "enabled": r.get("enabled", True),
                "editable": editable_rule(r, (config.get("api") or {}).get("tag")),
            }
            for i, r in enumerate(routing.get("rules", [])[:100])
        ]
        return {
            "readable": True,
            "fingerprint": fingerprint(config),
            "outbounds": outbounds,
            "balancers": balancers,
            "rules": rules,
        }
    except (OSError, ValueError, TypeError, KeyError, AttributeError, sqlite3.Error):
        return empty

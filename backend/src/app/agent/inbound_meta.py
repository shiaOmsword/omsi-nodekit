"""Public configuration fingerprints; no identity material leaves the VPS."""

import hashlib
import json
import re


def object_value(value):
    result = json.loads(value or "{}") if isinstance(value, str) else value or {}
    if not isinstance(result, dict):
        raise ValueError()
    return result


def public_inbound(value):
    stream = object_value(value.get("streamSettings", value.get("stream_settings")))
    reality = stream.get("realitySettings") or {}
    names = reality.get("serverNames") or []
    target = reality.get("dest") or reality.get("target") or ""
    if not isinstance(target, str) or not re.fullmatch(r"[a-zA-Z0-9.\-:\[\]]{0,260}", target):
        target = ""
    item = {
        "id": int(value["id"]),
        "remark": str(value.get("remark") or "")[:160],
        "protocol": str(value.get("protocol") or "")[:32],
        "port": int(value["port"]),
        "listen": str(value.get("listen") or "0.0.0.0")[:80],
        "enabled": bool(value.get("enable", value.get("enabled", False))),
        "network": str(stream.get("network", ""))[:32],
        "security": str(stream.get("security", ""))[:32],
        "tag": str(value.get("tag") or "")[:160],
        "server_names": [str(v)[:253] for v in names[:16] if isinstance(v, str)],
        "target": target,
    }
    item["fingerprint"] = hashlib.sha256(
        json.dumps(item, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return item

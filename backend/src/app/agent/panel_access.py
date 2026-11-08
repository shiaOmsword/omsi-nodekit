"""Private panel addressing and redacted status shared by agent operations."""

import ipaddress
import json


def panel_bind(node):
    access = node["caddy"].get("panel_access") or {}
    if access.get("mode", "disabled") != "disabled":
        return (node.get("deployment") or {}).get("subscription_bind", "127.0.0.1")
    return "127.0.0.1"


def panel_url(node):
    caddy = node["caddy"]
    suffix = "" if caddy["https_port"] == 443 else f":{caddy['https_port']}"
    return f"https://{caddy['domain']}{suffix}{node['panel']['base_path']}"


def access_status(context, inspector):
    result = {
        "mode": "disabled",
        "configured": False,
        "backend_host": "127.0.0.1",
        "public_url": None,
    }
    if inspector.selected:
        try:
            address = ipaddress.ip_address(
                inspector.selected.get("settings", {}).get("webListen", "")
            )
            if address.is_private and not address.is_unspecified and not address.is_multicast:
                result["backend_host"] = str(address)
        except ValueError:
            pass
    if not inspector.selected or inspector.selected.get("installation") != "managed":
        return result
    try:
        path = context.directory() / "manifest.json"
        if (
            context.directory().is_symlink()
            or path.is_symlink()
            or path.stat().st_size > context.discovery["metadata_bytes"]
        ):
            return result
        saved = json.loads(path.read_text(encoding="utf-8"))["node"]
        if saved["id"] != context.node["id"]:
            return result
        defaults = {"mode": "disabled", "username": None, "password_hash": None, "allowed_ips": []}
        applied = {**defaults, **(saved["caddy"].get("panel_access") or {})}
        desired = {**defaults, **(context.node["caddy"].get("panel_access") or {})}
        result["mode"] = applied.get("mode", "disabled")
        result["configured"] = (
            applied == desired
            and inspector.selected.get("settings", {}).get("webListen") == panel_bind(saved)
            and all(
                saved["caddy"].get(k) == context.node["caddy"].get(k)
                for k in ("domain", "https_port")
            )
            and all(
                saved["panel"].get(k) == context.node["panel"].get(k) for k in ("port", "base_path")
            )
        )
        if result["mode"] != "disabled":
            result["public_url"] = panel_url(saved)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        pass
    return result

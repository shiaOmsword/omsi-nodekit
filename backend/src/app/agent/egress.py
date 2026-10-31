"""Redacted Xray routing inventory and bounded IPv4 HTTPS probes."""

import json
import platform
import re
from urllib.parse import urlsplit

from framework.messages import MessageKey
from framework.messages import text as message_text

TARGETS = ("https://example.com/", "https://www.google.com/generate_204")


def runtime_paths(context, inspector):
    finding = inspector.selected
    if not finding or finding["installation"] != "managed":
        return None, None
    arch = {"x86_64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine())
    if not arch:
        return None, None
    filename = f"xray-linux-{arch}"
    if finding.get("container"):
        container = inspector.panels.containers.get(finding["id"])
        if not container:
            return None, None
        directory = (container.get("Config") or {}).get("WorkingDir") or "/app"
        for value in (container.get("Config") or {}).get("Env", []):
            if value.startswith("XUI_BIN_FOLDER=/"):
                directory = value.split("=", 1)[1]
                break
        else:
            directory = directory.rstrip("/") + "/bin"
        return (
            inspector.inventory.container_path(container, directory + "/config.json"),
            inspector.inventory.container_path(container, directory + "/" + filename),
        )
    directory = context.directory() / "runtime/bin"
    return directory / "config.json", directory / filename


def routing_inventory(context, inspector):
    try:
        path, _ = runtime_paths(context, inspector)
        if (
            not path
            or not path.is_file()
            or path.stat().st_size > context.discovery["metadata_bytes"]
        ):
            return {"readable": False, "outbounds": [], "rules": [], "warnings": []}
        config = json.loads(path.read_text(encoding="utf-8"))
        outbounds = []
        for item in config.get("outbounds", [])[:100]:
            via = (item.get("proxySettings") or {}).get("tag") or (
                item.get("streamSettings") or {}
            ).get("sockopt", {}).get("dialerProxy")
            outbounds.append(
                {
                    "tag": str(item.get("tag", ""))[:160],
                    "protocol": str(item.get("protocol", ""))[:32],
                    "via": str(via)[:160] if via else None,
                }
            )
        rules = [
            {
                "index": index,
                "inbound_tags": [str(v)[:160] for v in item.get("inboundTag", [])[:32]],
                "outbound_tag": str(item.get("outboundTag", ""))[:160],
                "balancer_tag": str(item.get("balancerTag", ""))[:160],
                "conditional": bool(
                    item.get("domain")
                    or item.get("ip")
                    or item.get("port")
                    or item.get("protocol")
                    or item.get("user")
                ),
            }
            for index, item in enumerate((config.get("routing") or {}).get("rules", [])[:100])
        ]
        tags = {o["tag"] for o in outbounds}
        missing = sorted(
            {
                r["outbound_tag"]
                for r in rules
                if r["outbound_tag"] and r["outbound_tag"] not in tags
            }
        )
        warnings = (
            ["В routing есть ссылки на отсутствующие outbound: " + ", ".join(missing)]
            if missing
            else []
        )
        for item in outbounds:
            if item["via"] and item["via"] not in tags:
                warnings.append(
                    "Outbound " + item["tag"] + " ссылается на отсутствующий dialer/proxy tag."
                )
        return {
            "readable": True,
            "outbounds": outbounds,
            "rules": rules,
            "default_tag": outbounds[0]["tag"] if outbounds else None,
            "warnings": warnings,
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {"readable": False, "outbounds": [], "rules": [], "warnings": []}


def curl_probe(context, url, *, socks_port=None):
    args = [
        "curl",
        "-4",
        "--silent",
        "--show-error",
        "--connect-timeout",
        "5",
        "--max-time",
        str(context.policy["probe_timeout"]),
        "--output",
        "/dev/null",
        "--write-out",
        "%{http_code}|%{time_total}|%{size_download}",
    ]
    if socks_port:
        args += ["--noproxy", "", "--proxy", f"socks5h://127.0.0.1:{socks_port}"]
    else:
        args += ["--noproxy", "*", "--proxy", ""]
    try:
        result = context.runner.completed(args + [url], timeout=context.policy["probe_timeout"] + 2)
        match = re.fullmatch(r"(\d{3})\|([\d.]+)\|([\d.]+)", result.stdout.strip())
        if result.returncode == 0 and match:
            status = int(match[1])
            return {
                "ok": 200 <= status < 400,
                "status": status,
                "seconds": float(match[2]),
                "bytes": int(float(match[3])),
                "reason": "HTTP " + str(status),
            }
        reason = {
            5: "DNS proxy",
            6: "DNS",
            7: "TCP connect",
            28: "timeout",
            35: "TLS handshake",
            60: "TLS certificate",
            97: "SOCKS/Xray outbound",
        }.get(result.returncode, "network/proxy")
        return {"ok": False, "reason": reason, "code": result.returncode}
    except (OSError, RuntimeError, ValueError):
        return {"ok": False, "reason": "probe unavailable"}


def egress_diagnostics(context, inspector):
    checks = []
    for url in TARGETS:
        result = curl_probe(context, url)
        item = {
            "name": "direct_https",
            "state": "ok" if result["ok"] else "error",
            "detail": urlsplit(url).hostname
            + " · IPv4 напрямую с VPS · "
            + result["reason"]
            + (f" · {result['seconds']:.2f} с" if result.get("seconds") is not None else ""),
        }
        checks.append(item)
        context.emit(
            message_text(MessageKey.NETWORK_CHECK, **item), "info" if result["ok"] else "error"
        )
    inspector.report.setdefault("network_checks", []).extend(checks)
    for warning in (inspector.report.get("egress") or {}).get("warnings", []):
        context.emit(
            message_text(MessageKey.NETWORK_CHECK, name="routing", state="warning", detail=warning),
            "warning",
        )
    return [c["detail"] for c in checks if c["state"] == "error"]

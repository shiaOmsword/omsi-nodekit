"""Check each subscription hop without putting client URLs or response bodies in reports."""

import fnmatch
import http.client
import ipaddress
import re
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from framework.messages import MessageKey
from framework.messages import text as message_text

from .panel_access import panel_bind


def public_base(node):
    caddy, panel = node["caddy"], node["panel"]
    suffix = "" if caddy["https_port"] == 443 else f":{caddy['https_port']}"
    return f"https://{caddy['domain']}{suffix}{panel['subscription_path']}"


def http_status(host, port, path, timeout, *, tls=False):
    connection_type = http.client.HTTPSConnection if tls else http.client.HTTPConnection
    connection = connection_type(host, port, timeout=timeout)
    try:
        connection.request("GET", path, headers={"Accept": "text/plain"})
        return connection.getresponse().status
    finally:
        connection.close()


def caddy_status(context, proxy, host, port, path):
    """Use Caddy's network namespace, rather than a misleading host-only TCP check."""
    if proxy["installation"] != "docker":
        return http_status(host, port, path, context.policy["http_timeout"])
    identifier = proxy["id"].split(":", 1)[1]
    address = ipaddress.ip_address(host)
    target = f"[{address}]" if address.version == 6 else str(address)
    result = context.runner.completed(
        [
            "docker",
            "exec",
            identifier,
            "wget",
            "-S",
            "-T",
            str(context.policy["http_timeout"]),
            "-O",
            "/dev/null",
            f"http://{target}:{port}{path}",
        ],
        timeout=context.policy["http_timeout"] + 2,
    )
    # wget reports HTTP errors on stderr and exits non-zero even for a normal 404.
    # Only status numbers escape this function, never URLs, headers or response bodies.
    output = result.stderr + result.stdout
    if len(output.encode()) > context.discovery["metadata_bytes"]:
        return None
    statuses = re.findall(r"^\s*HTTP/\S+\s+(\d{3})\b", output, re.MULTILINE)
    if not statuses or any(300 <= int(s) < 400 for s in statuses):
        return None
    return int(statuses[-1])


def verify_caddy_upstream(context, proxy):
    target = context.node["deployment"]
    host, port = target["subscription_bind"], context.node["panel"]["subscription_port"]
    try:
        status = caddy_status(
            context,
            proxy,
            host,
            port,
            context.node["panel"]["subscription_path"] + "nodekit-healthcheck",
        )
        if status is None or not (200 <= status < 300 or 400 <= status < 500):
            raise ValueError()
    except (OSError, ValueError, RuntimeError, http.client.HTTPException) as exc:
        raise RuntimeError(
            message_text(MessageKey.SUBSCRIPTION_PROBE_FAILED, host=host, port=port)
        ) from exc


def verify_panel_upstream(context, proxy):
    if (context.node["caddy"].get("panel_access") or {}).get("mode", "disabled") == "disabled":
        return
    try:
        status = caddy_status(
            context,
            proxy,
            panel_bind(context.node),
            context.node["panel"]["port"],
            context.node["panel"]["base_path"],
        )
        if status != 200:
            raise ValueError()
    except (OSError, ValueError, RuntimeError, http.client.HTTPException) as exc:
        raise RuntimeError(message_text(MessageKey.PANEL_ACCESS_FAILED)) from exc
    context.emit(message_text(MessageKey.PANEL_ACCESS_READY))


def preflight_caddy_network(context, proxy):
    """Prove bridge→host access on the actual port before installing anything."""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    address = context.node["deployment"]["subscription_bind"]
    port = context.node["panel"]["subscription_port"]
    try:
        with ThreadingHTTPServer((address, port), Handler) as server:
            server.daemon_threads = True
            worker = threading.Thread(
                target=lambda: server.serve_forever(poll_interval=0.05), daemon=True
            )
            worker.start()
            try:
                verify_caddy_upstream(context, proxy)
            finally:
                server.shutdown()
                worker.join(timeout=2)
    except OSError as exc:
        raise RuntimeError(message_text(MessageKey.PORT_OCCUPIED, port=port)) from exc


class SubscriptionDiagnostics:
    def __init__(self, context, inspector):
        self.context, self.inspector = context, inspector
        self.checks = []

    def record(self, name, state, detail):
        item = {"name": name, "state": state, "detail": detail}
        self.checks.append(item)
        self.context.emit(
            message_text(MessageKey.SUBSCRIPTION_CHECK, **item),
            "error" if state == "error" else "warning" if state == "warning" else "info",
        )

    def check(self):
        from .existing_diagnostics import ExistingDiagnostics

        finding = self.inspector.selected
        if not finding or not finding.get("active") or not finding.get("settings"):
            return []
        settings = finding["settings"]
        if settings.get("subEnable", "false").lower() != "true":
            return []
        probe_id = self.inspector.panels.probe_ids.get(finding["id"])
        path = settings.get("subPath", "/sub/") + (probe_id or "nodekit-healthcheck")
        endpoint = ExistingDiagnostics(self.context, self.inspector)._endpoint(finding, "sub")
        if settings.get("subCertFile"):
            self.record(
                "upstream",
                "not_checked",
                "Встроенный TLS проверяется диагностикой панели; HTTP-проверка пропущена.",
            )
        elif endpoint:
            try:
                status = http_status(*endpoint, path, self.context.policy["http_timeout"])
                self._status("upstream", status, probe_id)
            except (OSError, ValueError, http.client.HTTPException):
                self.record(
                    "upstream",
                    "error",
                    "HTTP-сервер подписок недоступен с хоста VPS; проверь subListen/subPort и журнал панели.",
                )
        else:
            self.record("upstream", "not_checked", "Не удалось определить HTTP-адрес подписок.")

        node = self.context.node
        base = settings.get("subURI") or (public_base(node) if node["caddy"]["enabled"] else None)
        try:
            parsed = urlsplit(base or "")
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or not re.fullmatch(r"[a-zA-Z0-9.-]+", parsed.hostname)
            ):
                raise ValueError()
            port = parsed.port or 443
            if not 1 <= port <= 65535:
                raise ValueError()
        except ValueError:
            self.record(
                "https",
                "not_checked",
                "Публичный HTTPS-адрес подписок не задан или не поддерживается.",
            )
            return self._finish()
        self.inspector.report["subscription_url_template"] = base + "<subscription-id>"
        proxies = self.inspector.report.get("caddy", [])
        selected_id = (node.get("deployment") or {}).get("caddy_id")
        proxy = next((p for p in proxies if p["id"] == selected_id), None)
        if proxy is None:
            candidates = [
                p
                for p in proxies
                if any(
                    any(fnmatch.fnmatchcase(parsed.hostname, h) for h in route.get("hosts", []))
                    for route in p.get("routes", [])
                )
            ]
            proxy = candidates[0] if len(candidates) == 1 else None
        if proxy:
            if finding.get("network_mode") == "host" or finding.get("service"):
                occupied = {
                    int(match[1])
                    for p in proxy.get("published_ports", [])
                    if (match := re.match(r"(?:0\.0\.0\.0|::):(\d+)->\d+/tcp$", p))
                }
                conflicts = sorted(
                    {
                        item["port"]
                        for item in finding.get("inbounds", [])
                        if item["enabled"] and item["port"] in occupied
                    }
                )
                if conflicts:
                    self.record(
                        "inbound_ports",
                        "warning",
                        "Порты inbound также опубликованы Caddy: "
                        + ", ".join(map(str, conflicts))
                        + ". Проверь конфликт listener; для нового inbound выбери свободный порт, например 8443.",
                    )
            published = (
                proxy["installation"] != "docker"
                or proxy.get("network_mode") == "host"
                or any(p.endswith(f":{port}->{port}/tcp") for p in proxy.get("published_ports", []))
            )
            self.record(
                "port",
                "ok" if published else "error",
                f"HTTPS-порт {port} опубликован/использует сеть хоста."
                if published
                else f"В Docker Caddy отсутствует публикация {port}:{port}/tcp; изменение URL не открывает порт.",
            )
            route_ok = endpoint and any(
                any(fnmatch.fnmatchcase(parsed.hostname, h) for h in r.get("hosts", []))
                and any(address.endswith(f":{port}") for address in r.get("listen", []))
                and f"{endpoint[0]}:{endpoint[1]}" in r.get("upstreams", [])
                and any(path.startswith(p.rstrip("*")) for p in r.get("paths", []))
                for r in proxy.get("routes", [])
            )
            self.record(
                "route",
                "ok" if route_ok else "warning",
                "В Caddyfile найден маршрут домен → путь подписок → HTTP-сервер."
                if route_ok
                else "Маршрут домена/порта/пути к серверу подписок не подтверждён по Caddyfile; проверь активную конфигурацию.",
            )
            if endpoint and not settings.get("subCertFile"):
                try:
                    self._status(
                        "caddy_upstream",
                        caddy_status(self.context, proxy, *endpoint, path),
                        probe_id,
                    )
                except (OSError, ValueError, RuntimeError, http.client.HTTPException):
                    self._status("caddy_upstream", None, probe_id)
        else:
            self.record(
                "route", "not_checked", "Не удалось однозначно выбрать Caddy для этого домена."
            )
        try:
            status = http_status(
                parsed.hostname,
                port,
                parsed.path + (probe_id or "nodekit-healthcheck"),
                self.context.policy["http_timeout"],
                tls=True,
            )
            self._status("https", status, probe_id)
        except ssl.SSLCertVerificationError:
            self.record(
                "https",
                "error",
                "Сертификат HTTPS не прошёл проверку доверия/имени/срока; проверь DNS и ACME в журнале Caddy.",
            )
        except (OSError, ValueError, http.client.HTTPException):
            self.record(
                "https",
                "error",
                "HTTPS подписок недоступен с VPS: проверь DNS, HTTPS-порт и журнал Caddy; доступ с внешнего клиента проверяется отдельно.",
            )
        return self._finish()

    def _status(self, name, status, probe_id):
        ok = (
            status == 200
            if probe_id
            else status is not None and (200 <= status < 300 or 400 <= status < 500)
        )
        if ok:
            self.record(
                name,
                "ok" if probe_id else "warning",
                "HTTP 200: получена выдача для существующего клиента; ссылка и содержимое скрыты."
                if probe_id
                else f"HTTP {status}: сервер отвечает, но нет клиента с subId для проверки настоящей подписки.",
            )
        else:
            self.record(
                name,
                "error",
                (f"HTTP {status}. " if status else "Нет HTTP-ответа. ")
                + (
                    "Caddy не может получить подписку: проверь listener и firewall между Docker-сетью и хостом."
                    if name == "caddy_upstream"
                    else "Проверь настройки подписок, маршрут Caddy и журнал сервиса."
                ),
            )

    def _finish(self):
        self.inspector.report["subscription_checks"] = self.checks
        return [c["detail"] for c in self.checks if c["state"] == "error"]

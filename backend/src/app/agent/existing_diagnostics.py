import http.client
import ipaddress
import socket
import ssl

from framework.messages import MessageKey
from framework.messages import text as message_text


class ExistingDiagnostics:
    def __init__(self, context, inspector):
        self.context = context
        self.inspector = inspector

    def _endpoint(self, finding, prefix):
        settings = finding["settings"]
        try:
            port = int(settings[f"{prefix}Port"])
            if not 1 <= port <= 65535:
                return None
        except (ValueError, KeyError):
            return None
        if finding["installation"] == "native" or finding.get("network_mode") == "host":
            host = settings.get(f"{prefix}Listen", "")
            return (
                "127.0.0.1" if host in {"", "0.0.0.0"} else "::1" if host == "::" else host,
                port,
            )
        container = self.inspector.panels.containers.get(finding["id"], {})
        bindings = container.get("NetworkSettings", {}).get("Ports", {}).get(f"{port}/tcp") or []
        # Pick loopback/wildcard first, then an explicitly bound host interface.
        bindings = sorted(
            bindings, key=lambda b: b.get("HostIp") not in {"127.0.0.1", "0.0.0.0", "::"}
        )
        for binding in bindings:
            try:
                host = binding.get("HostIp", "0.0.0.0")
                host = "127.0.0.1" if host in {"", "0.0.0.0"} else "::1" if host == "::" else host
                ipaddress.ip_address(host)
                return host, int(binding["HostPort"])
            except (ValueError, KeyError):
                continue
        return None

    def _socket(self, endpoint, settings, prefix):
        connection = socket.create_connection(endpoint, timeout=self.context.policy["http_timeout"])
        if not settings.get(f"{prefix}CertFile"):
            return connection
        # Connect locally but use the configured panel/subscription domain for SNI/verification.
        hostname = settings.get(f"{prefix}Domain") or endpoint[0]
        try:
            return ssl.create_default_context().wrap_socket(connection, server_hostname=hostname)
        except Exception:
            connection.close()
            raise

    def check(self):
        finding = self.inspector.selected
        if finding is None:
            raise RuntimeError(message_text(MessageKey.INSPECTION_REQUIRED))
        if not finding["active"]:
            raise RuntimeError(message_text(MessageKey.PANEL_NOT_RUNNING))
        settings = finding["settings"]
        if "webPort" not in settings or "webBasePath" not in settings:
            raise RuntimeError(message_text(MessageKey.INSPECTION_CONFIG_INCOMPLETE))
        failures = []
        for cert in finding["certificates"]:
            if cert["state"] in {"missing", "expired", "not_yet_valid", "invalid"}:
                failures.append(message_text(MessageKey.PANEL_TLS_FAILED))
            elif cert["state"] == "unknown":
                self.context.emit(message_text(MessageKey.CERTIFICATE_UNKNOWN), "warning")
        endpoint = self._endpoint(finding, "web")
        if endpoint is None:
            failures.append(message_text(MessageKey.PANEL_ENDPOINT_UNAVAILABLE))
        else:
            try:
                connection = http.client.HTTPConnection(
                    *endpoint, timeout=self.context.policy["http_timeout"]
                )
                with self._socket(endpoint, settings, "web") as stream:
                    connection.sock = stream
                    try:
                        connection.request(
                            "GET",
                            settings["webBasePath"],
                            headers={"Host": settings.get("webDomain") or endpoint[0]},
                        )
                        response = connection.getresponse()
                        if not 200 <= response.status < 400:
                            raise RuntimeError(
                                message_text(MessageKey.HTTP_STATUS, status=response.status)
                            )
                    finally:
                        connection.close()
                self.context.emit(
                    message_text(
                        MessageKey.PANEL_HTTPS_OK
                        if settings.get("webCertFile")
                        else MessageKey.PANEL_HTTP_OK
                    )
                )
            except (OSError, ValueError, RuntimeError, http.client.HTTPException) as exc:
                failures.append(
                    message_text(MessageKey.PANEL_HTTP_FAILED, reason=type(exc).__name__)
                )
        if settings.get("subEnable", "false").lower() != "true":
            self.context.emit(message_text(MessageKey.SUBSCRIPTION_DISABLED))
        else:
            endpoint = self._endpoint(finding, "sub")
            if endpoint is None:
                failures.append(message_text(MessageKey.PANEL_ENDPOINT_UNAVAILABLE))
            else:
                try:
                    with self._socket(endpoint, settings, "sub"):
                        pass
                    self.context.emit(message_text(MessageKey.SUBSCRIPTION_TCP_OK))
                except (OSError, ValueError):
                    failures.append(message_text(MessageKey.SUBSCRIPTION_TCP_FAILED))
        for failure in dict.fromkeys(failures):
            self.context.emit(failure, "error")
        if failures:
            raise RuntimeError(message_text(MessageKey.DIAGNOSTICS_FAILED, count=len(failures)))

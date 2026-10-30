"""Read-only doctor checks against the actual selected 3x-ui installation.

Never assume a managed port from YAML is the live listener.  A TLS trust
failure is reported as *unverified*, not retried with certificate checks off.
"""

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
        except (ValueError, TypeError, KeyError):
            return None

        if finding["installation"] == "native" or finding.get("network_mode") == "host":
            listen = settings.get(f"{prefix}Listen", "")
            return (
                "127.0.0.1" if listen in {"", "0.0.0.0"} else "::1" if listen == "::" else listen,
                port,
            )

        container = self.inspector.panels.containers.get(finding["id"], {})
        network = container.get("NetworkSettings") or {}
        bindings = (network.get("Ports") or {}).get(f"{port}/tcp") or []
        bindings = sorted(
            bindings, key=lambda b: b.get("HostIp") not in {"127.0.0.1", "0.0.0.0", "::"}
        )
        for binding in bindings:
            try:
                host = binding.get("HostIp", "0.0.0.0")
                host = "127.0.0.1" if host in {"", "0.0.0.0"} else "::1" if host == "::" else host
                ipaddress.ip_address(host)
                host_port = int(binding["HostPort"])
                if 1 <= host_port <= 65535:
                    return host, host_port
            except (ValueError, TypeError, KeyError):
                continue

        # On a Linux host the bridge IP may be reachable even without published
        # ports (for example when Caddy is on the same private Docker network).
        # A listener bound to container loopback cannot be probed this way.
        listen = settings.get(f"{prefix}Listen", "")
        if listen in {"127.0.0.1", "::1", "localhost"}:
            return None
        for item in (network.get("Networks") or {}).values():
            for key in ("IPAddress", "GlobalIPv6Address"):
                address = item.get(key)
                if not address:
                    continue
                try:
                    ipaddress.ip_address(address)
                    return address, port
                except ValueError:
                    continue
        return None

    def _socket(self, endpoint, settings, prefix):
        connection = socket.create_connection(endpoint, timeout=self.context.policy["http_timeout"])
        if not settings.get(f"{prefix}CertFile"):
            return connection
        # Use the configured domain as TLS SNI and verify its certificate/CA.
        # Never silently switch to an unverified SSL context.
        hostname = settings.get(f"{prefix}Domain") or endpoint[0]
        try:
            return ssl.create_default_context().wrap_socket(connection, server_hostname=hostname)
        except Exception:
            connection.close()
            raise

    def _record(self, failures, key, *, level="error", **values):
        message = message_text(key, **values)
        self.context.emit(message, level)
        if level == "error":
            failures.append(message)

    def _certificate(self, finding, usage, failures):
        for certificate in finding["certificates"]:
            if certificate["usage"] != usage:
                continue
            if certificate["state"] in {"missing", "expired", "not_yet_valid", "invalid"}:
                self._record(failures, MessageKey.PANEL_TLS_FAILED)
            elif certificate["state"] == "unknown":
                self._record(failures, MessageKey.CERTIFICATE_UNKNOWN, level="warning")

    @staticmethod
    def _inferred(finding, *names):
        return any(name in finding.get("defaulted_settings", []) for name in names)

    def check(self, *, raise_on_failure=True):
        failures = []
        finding = self.inspector.selected
        if finding is None:
            self._record(failures, MessageKey.INSPECTION_REQUIRED)
            return self._finish(failures, raise_on_failure)

        caddy = self.inspector.report["caddy"] if self.inspector.report else []
        self._record(
            failures,
            MessageKey.DOCTOR_SCOPE,
            level="info",
            installation=finding["installation"],
            caddy=len(caddy),
            active=sum(bool(item["active"]) for item in caddy),
        )
        if caddy:
            self._record(failures, MessageKey.DOCTOR_CADDY_UNVERIFIED, level="warning")
        if self.context.node["caddy"]["enabled"] and not any(x["active"] for x in caddy):
            self._record(failures, MessageKey.DOCTOR_CADDY_NOT_RUNNING)

        for warning in finding.get("warnings", []):
            self.context.emit(warning, "warning")

        if not finding["active"]:
            self._record(failures, MessageKey.PANEL_NOT_RUNNING)
            return self._finish(failures, raise_on_failure)

        settings = finding["settings"]
        if not settings or "webPort" not in settings or "webBasePath" not in settings:
            self._record(failures, MessageKey.INSPECTION_CONFIG_INCOMPLETE)
            return self._finish(failures, raise_on_failure)

        self._certificate(finding, "panel", failures)
        endpoint = self._endpoint(finding, "web")
        web_inferred = self._inferred(finding, "webPort", "webBasePath")
        if web_inferred:
            self._record(failures, MessageKey.DOCTOR_WEB_DEFAULTED, level="warning")
        if endpoint is None:
            level = "warning" if finding["installation"] != "native" or web_inferred else "error"
            self._record(failures, MessageKey.PANEL_ENDPOINT_UNAVAILABLE, level=level)
        else:
            scheme = "HTTPS" if settings.get("webCertFile") else "HTTP"
            self._record(
                failures,
                MessageKey.DOCTOR_ENDPOINT,
                level="info",
                service="Panel",
                scheme=scheme,
                host=endpoint[0],
                port=endpoint[1],
            )
            connection = http.client.HTTPConnection(
                *endpoint, timeout=self.context.policy["http_timeout"]
            )
            try:
                with self._socket(endpoint, settings, "web") as stream:
                    connection.sock = stream
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
                self._record(
                    failures,
                    MessageKey.PANEL_HTTPS_OK if scheme == "HTTPS" else MessageKey.PANEL_HTTP_OK,
                    level="info",
                )
            except ssl.SSLCertVerificationError:
                self._record(failures, MessageKey.DOCTOR_WEB_TLS_UNTRUSTED, level="warning")
            except (OSError, ValueError, RuntimeError, http.client.HTTPException) as exc:
                self._record(
                    failures,
                    MessageKey.PANEL_HTTP_FAILED,
                    level="warning" if web_inferred else "error",
                    reason=type(exc).__name__,
                )
            finally:
                connection.close()

        if settings.get("subEnable", "false").lower() != "true":
            self._record(failures, MessageKey.SUBSCRIPTION_DISABLED, level="info")
        else:
            self._certificate(finding, "subscription", failures)
            inferred = self._inferred(finding, "subEnable", "subPort", "subListen")
            if inferred:
                self._record(failures, MessageKey.DOCTOR_SUB_DEFAULTED, level="warning")
            endpoint = self._endpoint(finding, "sub")
            if endpoint is None:
                self._record(
                    failures,
                    MessageKey.DOCTOR_SUB_UNREACHABLE,
                    level="warning" if inferred or finding["installation"] != "native" else "error",
                )
            else:
                scheme = "TLS" if settings.get("subCertFile") else "TCP"
                self._record(
                    failures,
                    MessageKey.DOCTOR_ENDPOINT,
                    level="info",
                    service="Subscription",
                    scheme=scheme,
                    host=endpoint[0],
                    port=endpoint[1],
                )
                try:
                    with self._socket(endpoint, settings, "sub"):
                        pass
                    self._record(failures, MessageKey.SUBSCRIPTION_TCP_OK, level="info")
                except ssl.SSLCertVerificationError:
                    self._record(failures, MessageKey.DOCTOR_SUB_TLS_UNTRUSTED, level="warning")
                except (OSError, ValueError) as exc:
                    self._record(
                        failures,
                        MessageKey.DOCTOR_SUB_TCP_FAILED,
                        level="warning" if inferred else "error",
                        reason=type(exc).__name__,
                    )

        return self._finish(failures, raise_on_failure)

    @staticmethod
    def _finish(failures, raise_on_failure):
        if failures and raise_on_failure:
            raise RuntimeError(message_text(MessageKey.DIAGNOSTICS_FAILED, count=len(failures)))
        return failures

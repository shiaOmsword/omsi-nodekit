import shutil
import urllib.error
import urllib.request

from framework.messages import MessageKey
from framework.messages import text as message_text

from .context import AgentContext
from .host import HostEnvironment


class Diagnostics:
    def __init__(self, context: AgentContext, host: HostEnvironment):
        self.context = context
        self.host = host

    def check(self, node, base):
        failures = []
        panel = node["panel"]
        url = f"http://127.0.0.1:{panel['port']}{panel['base_path']}"
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(url, timeout=self.context.policy["http_timeout"]) as response:
                if response.status != 200:
                    raise RuntimeError(message_text(MessageKey.HTTP_STATUS, status=response.status))
            self.context.emit(message_text(MessageKey.PANEL_HTTP_OK))
        except (OSError, urllib.error.URLError, RuntimeError) as exc:
            failures.append(message_text(MessageKey.PANEL_HTTP_FAILED, reason=exc))
        if self.host.port_open(panel["subscription_port"]):
            self.context.emit(message_text(MessageKey.SUBSCRIPTION_TCP_OK))
        else:
            failures.append(message_text(MessageKey.SUBSCRIPTION_TCP_FAILED))
        for failure in failures:
            self.context.emit(failure, "error")
        if failures:
            raise RuntimeError(message_text(MessageKey.DIAGNOSTICS_FAILED, count=len(failures)))
        self.check_transport(node)

    def check_transport(self, node, *, raise_on_failure=True):
        failures = []
        for tunnel in node["tunnels"]:
            unit = self.context.unit(tunnel["name"])
            state = self.context.status(["systemctl", "is-active", "--quiet", unit])
            if state or not self.host.port_open(tunnel["local_port"]):
                failures.append(message_text(MessageKey.TUNNEL_FAILED, name=tunnel["name"]))
            else:
                self.context.emit(message_text(MessageKey.TUNNEL_AVAILABLE, name=tunnel["name"]))
        if node.get("probe"):
            if not shutil.which("curl"):
                failures.append(message_text(MessageKey.PROBE_CURL_REQUIRED))
            else:
                probe = node["probe"]
                try:
                    self.context.command(
                        [
                            "curl",
                            "--noproxy",
                            "",
                            "--fail",
                            "--silent",
                            "--show-error",
                            "--max-time",
                            str(self.context.policy["probe_timeout"]),
                            "--proxy",
                            f"socks5h://127.0.0.1:{probe['socks_port']}",
                            probe["url"],
                        ],
                        timeout=self.context.policy["probe_timeout"] + 5,
                    )
                    self.context.emit(message_text(MessageKey.PROXY_HTTPS_OK))
                except RuntimeError as exc:
                    failures.append(message_text(MessageKey.PROXY_PROBE_FAILED, reason=exc))
        else:
            self.context.emit(message_text(MessageKey.PROBE_NOT_CONFIGURED), "warning")
        if node["caddy"]["enabled"]:
            self.context.emit(
                message_text(MessageKey.EXTERNAL_CHECK_REQUIRED),
                "warning",
            )
        for failure in failures:
            self.context.emit(failure, "error")
        if failures and raise_on_failure:
            raise RuntimeError(message_text(MessageKey.DIAGNOSTICS_FAILED, count=len(failures)))
        return failures

import shutil
import urllib.error
import urllib.request

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
                    raise RuntimeError(f"HTTP {response.status}")
            self.context.emit("Panel HTTP: OK")
        except (OSError, urllib.error.URLError, RuntimeError) as exc:
            failures.append(f"Panel HTTP: {exc}")
        if self.host.port_open(panel["subscription_port"]):
            self.context.emit(
                "Subscription backend TCP: OK (a real client subscription is not tested)"
            )
        else:
            failures.append("Subscription backend TCP: unavailable")
        for tunnel in node["tunnels"]:
            unit = self.context.unit(tunnel["name"])
            state = self.context.status(["systemctl", "is-active", "--quiet", unit])
            if state or not self.host.port_open(tunnel["local_port"]):
                failures.append(f"Tunnel {tunnel['name']}: unavailable")
            else:
                self.context.emit(
                    f"Tunnel {tunnel['name']}: process/listener OK; data path not verified"
                )
        if node.get("probe"):
            if not shutil.which("curl"):
                failures.append("End-to-end probe requires curl on the VPS")
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
                    self.context.emit("HTTPS request through configured SOCKS outbound: OK")
                except RuntimeError as exc:
                    failures.append(f"End-to-end probe: {exc}")
        else:
            self.context.emit("End-to-end proxy probe: NOT CONFIGURED", "warning")
        if node["caddy"]["enabled"]:
            self.context.emit(
                "Public DNS, ACME certificate and client-side connectivity require an external check",
                "warning",
            )
        for failure in failures:
            self.context.emit(failure, "error")
        if failures:
            raise RuntimeError(f"Diagnostics found {len(failures)} failure(s)")

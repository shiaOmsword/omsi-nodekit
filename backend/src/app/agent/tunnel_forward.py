"""An owned loopback-only systemd SSH forward, with reversible activation."""

from pathlib import Path


class TunnelForward:
    def __init__(self, context, host, tunnel):
        self.context, self.host, self.tunnel = context, host, tunnel
        self.unit = context.unit(tunnel["name"])
        self.path = Path(context.policy["unit_directory"]) / self.unit
        self.content = context.payload["files"][self.unit]
        self.created = self.touched = False
        self.active = self.enabled = False

    def preflight(self):
        context, tunnel = self.context, self.tunnel
        if self.path.is_symlink() or (
            self.path.exists() and self.path.read_text(encoding="utf-8") != self.content
        ):
            raise ValueError()
        fragment = context.command(
            ["systemctl", "show", "-p", "FragmentPath", "--value", self.unit]
        )
        if fragment and Path(fragment) != self.path:
            raise ValueError()
        for key in ("identity_file", "known_hosts_file"):
            context.command(["runuser", "-u", tunnel["user"], "--", "test", "-r", tunnel[key]])
        self.enabled = context.status(["systemctl", "is-enabled", "--quiet", self.unit]) == 0
        self.active = context.status(["systemctl", "is-active", "--quiet", self.unit]) == 0
        if not self.active:
            self.host.require_endpoint(tunnel["local_port"], "127.0.0.1")

    def start(self):
        if not self.path.exists():
            with self.path.open("x", encoding="utf-8") as file:
                file.write(self.content)
            self.created = True
            self.path.chmod(0o644)
            self.context.command(["systemctl", "daemon-reload"])
        self.touched = True
        self.context.command(["systemctl", "enable", "--now", self.unit])

    def ready(self):
        return self.context.status(
            ["systemctl", "is-active", "--quiet", self.unit]
        ) == 0 and self.host.port_open(self.tunnel["local_port"])

    def rollback(self):
        # A rejected preflight must never stop or disable somebody else's unit.
        if not (self.touched or self.created):
            return
        if self.path.is_symlink() or self.path.read_text(encoding="utf-8") != self.content:
            raise ValueError()
        if not self.active:
            self.context.command(["systemctl", "stop", self.unit])
        if not self.enabled:
            self.context.command(["systemctl", "disable", self.unit])
        if self.created:
            self.path.unlink()
            self.context.command(["systemctl", "daemon-reload"])

"""An owned loopback-only systemd SSH forward, with reversible activation."""

from pathlib import Path, PurePosixPath

from framework.messages import MessageKey
from framework.messages import text as message_text

from .tunnel_errors import TunnelPreflightError


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
            raise TunnelPreflightError(message_text(MessageKey.TUNNEL_UNIT_CHANGED, unit=self.unit))
        try:
            fragment = context.command(
                ["systemctl", "show", "-p", "FragmentPath", "--value", self.unit]
            )
        except RuntimeError as exc:
            raise TunnelPreflightError(
                message_text(MessageKey.TUNNEL_SYSTEMD_FAILED, unit=self.unit)
            ) from exc
        if fragment and Path(fragment) != self.path:
            raise TunnelPreflightError(message_text(MessageKey.TUNNEL_UNIT_CHANGED, unit=self.unit))

        def require_permission(flag, path, key=MessageKey.TUNNEL_KEY_UNREADABLE):
            try:
                context.command(["runuser", "-u", tunnel["user"], "--", "test", flag, path])
            except RuntimeError as exc:
                raise TunnelPreflightError(
                    message_text(key, user=tunnel["user"], path=path)
                ) from exc

        require_permission("-r", tunnel["identity_file"])
        known_hosts = tunnel["known_hosts_file"]
        if tunnel.get("host_key_policy", "strict") == "accept-new":
            # A new SSH port is a separate trust entry. Accept only an unseen
            # key and ensure the service user can persist that trust decision.
            if context.status(["test", "-L", known_hosts]) == 0:
                raise TunnelPreflightError(
                    message_text(
                        MessageKey.TUNNEL_KNOWN_HOSTS_UNWRITABLE,
                        user=tunnel["user"],
                        path=known_hosts,
                    )
                )
            if context.status(["test", "-e", known_hosts]) == 0:
                require_permission("-r", known_hosts)
                require_permission("-w", known_hosts, MessageKey.TUNNEL_KNOWN_HOSTS_UNWRITABLE)
            else:
                parent = str(PurePosixPath(known_hosts).parent)
                for flag in ("-d", "-w", "-x"):
                    require_permission(flag, parent, MessageKey.TUNNEL_KNOWN_HOSTS_UNWRITABLE)
        else:
            # Strict mode requires a preapproved, readable host key.
            require_permission("-r", known_hosts)
        self.enabled = context.status(["systemctl", "is-enabled", "--quiet", self.unit]) == 0
        self.active = context.status(["systemctl", "is-active", "--quiet", self.unit]) == 0
        if not self.active:
            try:
                self.host.require_endpoint(tunnel["local_port"], "127.0.0.1")
            except RuntimeError as exc:
                raise TunnelPreflightError(
                    message_text(MessageKey.TUNNEL_LOCAL_PORT_BUSY, port=tunnel["local_port"])
                ) from exc

    def start(self):
        if self.path.is_symlink() or (
            self.path.exists() and self.path.read_text(encoding="utf-8") != self.content
        ):
            raise TunnelPreflightError(message_text(MessageKey.TUNNEL_UNIT_CHANGED, unit=self.unit))
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
            raise TunnelPreflightError(message_text(MessageKey.TUNNEL_UNIT_CHANGED, unit=self.unit))
        if not self.active:
            self.context.command(["systemctl", "stop", self.unit])
        if not self.enabled:
            self.context.command(["systemctl", "disable", self.unit])
        if self.created:
            self.path.unlink()
            self.context.command(["systemctl", "daemon-reload"])

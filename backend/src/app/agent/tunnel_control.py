import time

from framework.messages import MessageKey
from framework.messages import text as message_text

from .tunnel_errors import TunnelPreflightError
from .tunnel_forward import TunnelForward


class TunnelController:
    def __init__(self, context, host):
        self.context, self.host = context, host

    def apply(self):
        context = self.context
        request = context.payload["options"]["tunnel_control"]
        names, operation = request["names"], request["operation"]
        configured = {t["name"]: t for t in context.node["tunnels"]}
        if (
            context.node["panel"]["installation"] != "managed"
            or not names
            or len(names) != len(set(names))
            or not set(names) <= configured.keys()
            or operation not in {"enable", "disable"}
        ):
            raise RuntimeError(message_text(MessageKey.TUNNEL_RESTART_REQUEST_INVALID))
        forwards = [TunnelForward(context, self.host, configured[name]) for name in names]
        for forward in forwards:
            forward.preflight(require_installed=True)
        touched = []
        try:
            for forward in forwards:
                forward.preflight(require_installed=True)
                touched.append(forward)
                context.command(["systemctl", operation, "--now", forward.unit])
                enabled = operation == "enable"
                for _ in range(context.policy["readiness_attempts"]):
                    active = (
                        context.status(["systemctl", "is-active", "--quiet", forward.unit]) == 0
                    )
                    autostart = (
                        context.status(["systemctl", "is-enabled", "--quiet", forward.unit]) == 0
                    )
                    if (
                        active == enabled
                        and autostart == enabled
                        and (not enabled or forward.ready())
                    ):
                        break
                    time.sleep(context.policy["readiness_interval"])
                else:
                    raise RuntimeError(
                        message_text(MessageKey.TUNNEL_CONTROL_FAILED, unit=forward.unit)
                    )
                context.emit(
                    message_text(
                        MessageKey.TUNNEL_CONTROL_APPLIED,
                        name=forward.tunnel["name"],
                        operation=operation,
                    )
                )
        except Exception as exc:
            failed_unit = forward.unit
            if isinstance(exc, TunnelPreflightError):
                context.emit(str(exc), "error")
            for forward in reversed(touched):
                try:
                    if (
                        forward.path.is_symlink()
                        or forward.path.read_text(encoding="utf-8") != forward.content
                    ):
                        raise ValueError()
                    context.command(
                        ["systemctl", "enable" if forward.enabled else "disable", forward.unit]
                    )
                    context.command(
                        ["systemctl", "start" if forward.active else "stop", forward.unit]
                    )
                except Exception:
                    context.emit(message_text(MessageKey.DEPLOYMENT_ROLLBACK_FAILED), "error")
            raise RuntimeError(
                message_text(MessageKey.TUNNEL_CONTROL_FAILED, unit=failed_unit)
            ) from exc

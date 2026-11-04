import time

from framework.messages import MessageKey
from framework.messages import text as message_text

from .tunnel_forward import TunnelForward


class TunnelRestarter:
    def __init__(self, context, host):
        self.context, self.host = context, host

    def apply(self):
        context = self.context
        request = (context.payload.get("options") or {}).get("tunnel_restart") or {}
        names = request.get("names")
        configured = {t["name"]: t for t in context.node["tunnels"]}
        if (
            context.node["panel"]["installation"] != "managed"
            or not isinstance(names, list)
            or not names
            or any(not isinstance(name, str) or name not in configured for name in names)
            or len(names) != len(set(names))
        ):
            raise RuntimeError(message_text(MessageKey.TUNNEL_RESTART_REQUEST_INVALID))
        forwards = [TunnelForward(context, self.host, configured[name]) for name in names]
        for forward in forwards:
            forward.preflight(require_installed=True)
        for forward in forwards:
            context.emit(message_text(MessageKey.TUNNEL_RESTART_BEGIN, unit=forward.unit))
            # Recheck ownership immediately before each mutation, including later batch members.
            forward.restart()
            for _ in range(context.policy["readiness_attempts"]):
                if forward.ready():
                    break
                time.sleep(context.policy["readiness_interval"])
            else:
                raise RuntimeError(
                    message_text(MessageKey.TUNNEL_RESTART_FAILED, unit=forward.unit)
                )
            context.emit(message_text(MessageKey.TUNNEL_RESTARTED, unit=forward.unit))

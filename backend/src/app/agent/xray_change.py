"""Compare-and-update transaction shared by independent Xray operations."""

import json
import time

from framework.messages import MessageKey
from framework.messages import text as message_text

from .inbound_manager import managed_api
from .tunnel_errors import TunnelPreflightError
from .tunnel_manager import private_write
from .xray_template import fingerprint


class XrayChange:
    def __init__(self, manager, base, expected):
        self.manager, self.base = manager, base
        self.context = manager.context
        self.api = managed_api(self.context, manager.inspector, base)
        self.original = manager.template(self.api)
        if fingerprint(self.original) != expected:
            raise TunnelPreflightError(message_text(MessageKey.XRAY_CONFIG_STALE))
        self.proposed = self.original
        self.attempted = False
        self.safe_to_stop = True
        self.writes = {}

    def __enter__(self):
        stamp = time.time_ns()
        self.manager.database.snapshot(
            self.manager.inspector.database(), self.base / f"before-xray-{stamp}.db"
        )
        private_write(self.base / f"before-xray-{stamp}.json", json.dumps(self.original).encode())
        return self

    def unchanged(self):
        if self.manager.template(self.api) != self.original:
            raise TunnelPreflightError(message_text(MessageKey.XRAY_CONFIG_STALE))

    def apply(self, proposed, verify):
        self.unchanged()
        self.proposed = proposed
        if proposed != self.original:
            self.attempted = True
            self.api.request("xray/update", {"xraySetting": json.dumps(proposed)}, form=True)
            if self.manager.template(self.api) != proposed:
                raise TunnelPreflightError(message_text(MessageKey.XRAY_CONFIG_STALE))
            self.api.request("server/restartXrayService", {})
        verify()

    def write(self, path, original, value):
        if path.is_symlink() or (path.read_bytes() if path.exists() else None) != original:
            raise TunnelPreflightError(message_text(MessageKey.XRAY_CONFIG_STALE))
        data = json.dumps(value).encode()
        private_write(path, data)
        self.writes[path] = (original, data)

    def __exit__(self, kind, error, traceback):
        if error is None:
            try:
                if self.manager.template(self.api) != self.proposed:
                    raise TunnelPreflightError(message_text(MessageKey.XRAY_CONFIG_STALE))
            except Exception as exc:
                error = exc
        if error is None:
            return False
        try:
            current = self.manager.template(self.api)
            if current == self.proposed and self.attempted:
                self.api.request(
                    "xray/update", {"xraySetting": json.dumps(self.original)}, form=True
                )
                self.api.request("server/restartXrayService", {})
                if self.manager.template(self.api) != self.original:
                    raise ValueError()
            elif current != self.original:
                raise ValueError()
        except Exception:
            self.safe_to_stop = False
            self.context.emit(message_text(MessageKey.DEPLOYMENT_ROLLBACK_FAILED), "error")
        for path, (original, written) in reversed(list(self.writes.items())):
            try:
                if path.is_symlink() or path.read_bytes() != written:
                    raise ValueError()
                if original is None:
                    path.unlink()
                else:
                    private_write(path, original)
            except Exception:
                self.context.emit(message_text(MessageKey.DEPLOYMENT_ROLLBACK_FAILED), "error")
        if kind is None:
            raise error
        return False


def run_xray_operation(manager, operation):
    try:
        operation()
    except TunnelPreflightError as exc:
        raise RuntimeError(str(exc)) from exc
    except Exception as exc:
        manager.context.emit(
            message_text(MessageKey.TUNNEL_ERROR_TYPE, kind=type(exc).__name__), "error"
        )
        raise RuntimeError(
            message_text(MessageKey.XRAY_CONFIG_FAILED, stage="configuration update")
        ) from exc
    manager.context.emit(message_text(MessageKey.XRAY_CONFIG_APPLIED))

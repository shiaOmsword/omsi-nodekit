import base64
import json
import os
import tempfile
from pathlib import Path

from app.defaults import XUI_DATABASE_FILE
from framework.messages import MessageKey
from framework.messages import text as message_text

from .adaptive_deployment import AdaptiveDeployment
from .backup_client_import import BackupClientImporter
from .configure import ConfigureSubscriptions
from .context import AgentContext
from .database import PanelDatabase
from .deployment import DeploymentService
from .diagnostics import Diagnostics
from .egress import egress_diagnostics
from .existing_diagnostics import ExistingDiagnostics
from .host import HostEnvironment
from .inbound_manager import InboundManager
from .inspection import InstallationInspector
from .subscription_maintenance import SubscriptionMaintenanceAgent
from .subscriptions import SubscriptionDiagnostics
from .tcp_tuning import TCPConfigurator
from .traffic_probe import TrafficProbe
from .tunnel_manager import TunnelManager
from .xhttp_manager import XHTTPManager


class RemoteAgent:
    def __init__(self, payload):
        self.context = AgentContext(payload)
        self.host = HostEnvironment(self.context)
        self.database = PanelDatabase(self.context)
        self.diagnostics = Diagnostics(self.context, self.host)
        self.deployment = DeploymentService(
            self.context, self.host, self.database, self.diagnostics
        )

    def run(self):
        os.umask(0o077)
        self.host.environment()
        import fcntl

        context = self.context
        action = context.payload["action"]
        base = context.directory()
        with open(context.policy["lock_file"], "w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError(message_text(MessageKey.REMOTE_OPERATION_RUNNING)) from exc
            inspector = InstallationInspector(context)
            if action in {"fresh", "restore"}:
                if context.node["panel"]["installation"] != "managed":
                    raise RuntimeError(message_text(MessageKey.EXISTING_READ_ONLY))
                report = inspector.inspect()
                if context.node.get("deployment"):
                    AdaptiveDeployment(
                        context, self.host, self.database, self.diagnostics, inspector
                    ).deploy(base)
                    inspector = InstallationInspector(context)
                    inspector.inspect()
                    return
                if context.node["caddy"]["enabled"] and report["caddy"]:
                    raise RuntimeError(message_text(MessageKey.CADDY_EXISTING_GUARD))
                self.deployment.deploy(context.payload, base)
            elif action == "doctor":
                inspector.inspect()
                # Always use actual discovered settings, including managed Docker panels.
                # Record every subsystem result before failing the aggregate doctor job.
                failures = ExistingDiagnostics(context, inspector).check(raise_on_failure=False)
                failures += SubscriptionDiagnostics(context, inspector).check()
                failures += egress_diagnostics(context, inspector)
                inspector.publish()
                failures += self.diagnostics.check_transport(context.node, raise_on_failure=False)
                if failures:
                    raise RuntimeError(
                        message_text(MessageKey.DIAGNOSTICS_FAILED, count=len(failures))
                    )
            elif action == "check":
                inspector.inspect()
                context.emit(message_text(MessageKey.ENVIRONMENT_CHECK_COMPLETED))
            elif action == "inbound":
                inspector.inspect()
                try:
                    InboundManager(context, self.host, self.database, inspector).apply(base)
                finally:
                    inspector = InstallationInspector(context)
                    inspector.inspect()
            elif action == "subscription_maintenance":
                inspector.inspect()
                SubscriptionMaintenanceAgent(context, self.host, self.database, inspector).apply(
                    base
                )
                inspector = InstallationInspector(context)
                inspector.inspect()
            elif action == "client_import":
                inspector.inspect()
                try:
                    BackupClientImporter(context, self.database, inspector).apply(base)
                finally:
                    inspector = InstallationInspector(context)
                    inspector.inspect()
            elif action == "xhttp":
                inspector.inspect()
                try:
                    XHTTPManager(context, self.host, self.database, inspector).apply(base)
                finally:
                    inspector = InstallationInspector(context)
                    inspector.inspect()
            elif action == "tunnel":
                inspector.inspect()
                try:
                    TunnelManager(context, self.host, self.database, inspector).apply(base)
                finally:
                    inspector = InstallationInspector(context)
                    inspector.inspect()
            elif action == "tcp_tuning":
                TCPConfigurator(context).apply()
            elif action == "traffic":
                inspector.inspect()
                try:
                    failures = TrafficProbe(context, self.host, inspector).run()
                    if failures:
                        raise RuntimeError(
                            message_text(MessageKey.DIAGNOSTICS_FAILED, count=len(failures))
                        )
                finally:
                    inspector.publish()
            elif action == "configure":
                inspector.inspect()
                ConfigureSubscriptions(
                    context, self.host, self.database, self.diagnostics, inspector
                ).apply(base)
                inspector = InstallationInspector(context)
                inspector.inspect()
                SubscriptionDiagnostics(context, inspector).check()
                inspector.publish()
            elif action == "backup":
                inspector.inspect()
                source = inspector.database()
                if not source.is_file():
                    raise RuntimeError(message_text(MessageKey.MANAGED_DATABASE_MISSING))
                with tempfile.TemporaryDirectory() as temporary:
                    destination = Path(temporary) / XUI_DATABASE_FILE
                    self.database.snapshot(source, destination)
                    if destination.stat().st_size > context.limits["backup_bytes"]:
                        raise RuntimeError(message_text(MessageKey.DATABASE_TOO_LARGE))
                    print(
                        json.dumps({"backup": base64.b64encode(destination.read_bytes()).decode()}),
                        flush=True,
                    )
                context.emit(message_text(MessageKey.BACKUP_DOWNLOADED))
            else:
                raise RuntimeError(message_text(MessageKey.ACTION_UNKNOWN))

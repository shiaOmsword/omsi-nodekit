from pydantic import Field, model_validator

from framework.messages import MessageKey
from framework.messages import text as message_text

from .base import StrictModel
from .network import (
    BackupClientImport,
    InboundChange,
    NetworkBenchmarkRequest,
    SubscriptionMaintenance,
    SystemRestoreRequest,
    TCPTuningRequest,
    TrafficRequest,
    TunnelRequest,
    TunnelRestartRequest,
    WireGuardChange,
    XHTTPChange,
)
from .records import JobAction


class JobRequest(StrictModel):
    action: JobAction
    backup_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    inbound: InboundChange | None = None
    wireguard: WireGuardChange | None = None
    traffic: TrafficRequest | None = None
    tcp_tuning: TCPTuningRequest | None = None
    system_restore: SystemRestoreRequest | None = None
    network_benchmark: NetworkBenchmarkRequest | None = None
    tunnel: TunnelRequest | None = None
    tunnel_restart: TunnelRestartRequest | None = None
    xhttp: XHTTPChange | None = None
    client_import: BackupClientImport | None = None
    subscription_maintenance: SubscriptionMaintenance | None = None

    @model_validator(mode="after")
    def operation_arguments(self):
        if (self.action == JobAction.WIREGUARD) != (self.wireguard is not None):
            raise ValueError(message_text(MessageKey.WIREGUARD_BACKUP_INVALID))
        if self.wireguard and (self.wireguard.operation == "restore") != bool(self.backup_id):
            raise ValueError(message_text(MessageKey.WIREGUARD_BACKUP_INVALID))
        if (self.action == JobAction.INBOUND) != (self.inbound is not None):
            raise ValueError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
        if (self.action == JobAction.SYSTEM_RESTORE) != (self.system_restore is not None):
            raise ValueError(message_text(MessageKey.SYSTEM_BACKUP_INVALID))
        if (self.action == JobAction.TCP_TUNING) != (self.tcp_tuning is not None):
            raise ValueError(message_text(MessageKey.TCP_TUNING_REQUEST_INVALID))
        if (self.action == JobAction.NETWORK_BENCHMARK) != (self.network_benchmark is not None):
            raise ValueError(message_text(MessageKey.NETWORK_BENCHMARK_INVALID))
        if (self.action == JobAction.TRAFFIC) != (self.traffic is not None):
            raise ValueError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
        if (self.action == JobAction.TUNNEL_RESTART) != (self.tunnel_restart is not None):
            raise ValueError(message_text(MessageKey.TUNNEL_RESTART_REQUEST_INVALID))
        if (self.action == JobAction.TUNNEL) != (self.tunnel is not None):
            raise ValueError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
        if (self.action == JobAction.XHTTP) != (self.xhttp is not None):
            raise ValueError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
        if (self.action == JobAction.CLIENT_IMPORT) != (self.client_import is not None):
            raise ValueError(message_text(MessageKey.BACKUP_CLIENTS_INVALID))
        if (self.action == JobAction.SUBSCRIPTION_MAINTENANCE) != (
            self.subscription_maintenance is not None
        ):
            raise ValueError(message_text(MessageKey.SUB_CACHE_REQUEST_INVALID))
        if (
            self.action in {JobAction.CLIENT_IMPORT, JobAction.SYSTEM_RESTORE}
            and not self.backup_id
        ):
            raise ValueError(message_text(MessageKey.RESTORE_BACKUP_REQUIRED))
        return self

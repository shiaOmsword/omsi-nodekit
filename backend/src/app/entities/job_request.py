from pydantic import Field, model_validator

from framework.messages import MessageKey
from framework.messages import text as message_text

from .base import StrictModel
from .network import BackupClientImport, InboundChange, TrafficRequest, TunnelRequest, XHTTPChange
from .records import JobAction


class JobRequest(StrictModel):
    action: JobAction
    backup_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    inbound: InboundChange | None = None
    traffic: TrafficRequest | None = None
    tunnel: TunnelRequest | None = None
    xhttp: XHTTPChange | None = None
    client_import: BackupClientImport | None = None

    @model_validator(mode="after")
    def operation_arguments(self):
        if (self.action == JobAction.INBOUND) != (self.inbound is not None):
            raise ValueError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
        if (self.action == JobAction.TRAFFIC) != (self.traffic is not None):
            raise ValueError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
        if (self.action == JobAction.TUNNEL) != (self.tunnel is not None):
            raise ValueError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
        if (self.action == JobAction.XHTTP) != (self.xhttp is not None):
            raise ValueError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
        if (self.action == JobAction.CLIENT_IMPORT) != (self.client_import is not None):
            raise ValueError(message_text(MessageKey.BACKUP_CLIENTS_INVALID))
        if self.action == JobAction.CLIENT_IMPORT and not self.backup_id:
            raise ValueError(message_text(MessageKey.RESTORE_BACKUP_REQUIRED))
        return self

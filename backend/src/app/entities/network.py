from typing import Literal

from pydantic import Field, field_validator, model_validator

from framework.messages import MessageKey
from framework.messages import text as message_text

from .base import Host, Port, Slug, StrictModel


class InboundChange(StrictModel):
    id: int = Field(gt=0)
    expected_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    operation: Literal["update", "delete", "add_client", "delete_client"] = "update"
    remark: str | None = Field(default=None, min_length=1, max_length=120)
    port: Port | None = None
    server_name: Host | None = None
    client_email: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.@-]{0,79}$")
    close_unmanaged_rule: bool = False

    @field_validator("remark")
    @classmethod
    def printable(cls, value):
        if value is not None and any(ord(c) < 32 for c in value):
            raise ValueError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
        return value

    @model_validator(mode="after")
    def changes(self):
        if self.operation == "delete" and any(
            x is not None for x in (self.remark, self.port, self.server_name)
        ):
            raise ValueError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
        if self.operation == "update" and all(
            x is None for x in (self.remark, self.port, self.server_name)
        ):
            raise ValueError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
        if self.operation in {"update", "delete"} and self.client_email is not None:
            raise ValueError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
        if self.operation in {"add_client", "delete_client"} and (
            not self.client_email
            or any(x is not None for x in (self.remark, self.port, self.server_name))
            or self.close_unmanaged_rule
        ):
            raise ValueError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
        return self


class TrafficRequest(StrictModel):
    id: int = Field(gt=0)
    expected_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class TunnelRequest(TrafficRequest):
    name: Slug
    outbound_tag: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_.-]+$")

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
    members: list[Slug] = Field(default_factory=list, max_length=6)
    pool_name: Slug | None = None

    @model_validator(mode="after")
    def pool_arguments(self):
        if self.members and (
            len(self.members) < 2
            or len(self.members) != len(set(self.members))
            or self.name != self.members[0]
            or self.pool_name is None
        ):
            raise ValueError(message_text(MessageKey.TUNNEL_CONFIG_INVALID))
        if not self.members and self.pool_name is not None:
            raise ValueError(message_text(MessageKey.TUNNEL_CONFIG_INVALID))
        return self


class XHTTPChange(StrictModel):
    """Managed XHTTP ingress. Private backend binds only to the Caddy host gateway."""

    operation: Literal["create", "update", "publish"] = "create"
    id: int | None = Field(default=None, gt=0)
    expected_fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    remark: str = Field(min_length=1, max_length=120)
    domain: Host
    port: Port
    path: str = Field(pattern=r"^/[a-zA-Z0-9_-]{1,64}/$")
    mode: Literal["auto", "packet-up", "stream-up"] = "auto"
    client_email: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.@-]{0,79}$")

    @model_validator(mode="after")
    def validate_change(self):
        if (
            (self.operation == "create" and (self.id is not None or self.expected_fingerprint))
            or (
                self.operation == "update"
                and (not self.id or not self.expected_fingerprint or self.client_email)
            )
            or ("." not in self.domain or ".." in self.domain)
        ):
            raise ValueError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
        if self.operation == "publish" and (not self.id or not self.expected_fingerprint or self.client_email):
            raise ValueError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
        if any(ord(c) < 32 for c in self.remark):
            raise ValueError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
        return self

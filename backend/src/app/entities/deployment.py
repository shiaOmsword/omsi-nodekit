"""Desired state is separate from the installation selected for discovery."""

import ipaddress
import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from framework.messages import MessageKey
from framework.messages import text as message_text

from .base import Host, Port, StrictModel


class TunnelInbound(StrictModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9-]{0,31}$")
    port: Port = 443
    listen: Literal["127.0.0.1", "0.0.0.0"] = "127.0.0.1"
    server_name: Host
    target_port: Port = 443
    client_email: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.@-]{0,79}$")


class DeploymentTarget(StrictModel):
    role: Literal["ingress", "exit"] = "exit"
    panel_runtime: Literal["native", "docker"] = "native"
    caddy_mode: Literal["none", "docker", "existing"] = "none"
    caddy_id: str | None = None
    subscription_bind: str = "127.0.0.1"
    install_docker: bool = False
    manage_ufw: bool = True
    manage_caddy_ports: bool = True
    inbounds: list[TunnelInbound] = Field(default_factory=list, max_length=12)

    @field_validator("subscription_bind")
    @classmethod
    def private_ipv4(cls, value):
        address = ipaddress.IPv4Address(value)
        if not address.is_private or address.is_unspecified or address.is_multicast:
            raise ValueError(message_text(MessageKey.DEPLOYMENT_BIND_INVALID))
        return str(address)

    @field_validator("caddy_id")
    @classmethod
    def identifier(cls, value):
        if value is not None and not re.fullmatch(
            r"(?:native|docker):[a-zA-Z0-9_.-]{1,128}", value
        ):
            raise ValueError(message_text(MessageKey.DEPLOYMENT_CADDY_SELECTION))
        return value

    @model_validator(mode="after")
    def unique_inbounds(self):
        if len({i.name for i in self.inbounds}) != len(self.inbounds):
            raise ValueError(message_text(MessageKey.DEPLOYMENT_INBOUNDS_DUPLICATE))
        if len({i.port for i in self.inbounds}) != len(self.inbounds):
            raise ValueError(message_text(MessageKey.DEPLOYMENT_INBOUNDS_DUPLICATE))
        if self.caddy_mode == "existing" and not self.caddy_id:
            raise ValueError(message_text(MessageKey.DEPLOYMENT_CADDY_SELECTION))
        if self.caddy_mode != "existing" and self.subscription_bind != "127.0.0.1":
            raise ValueError(message_text(MessageKey.DEPLOYMENT_BIND_INVALID))
        return self


class DiscoverySelection(StrictModel):
    yaml: str
    job_id: str
    panel_id: str | None = None
    caddy_id: str | None = None
    role: Literal["ingress", "exit"] = "exit"


class DeploymentSelection(StrictModel):
    yaml: str
    target: DeploymentTarget

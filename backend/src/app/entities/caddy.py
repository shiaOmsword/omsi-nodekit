import ipaddress
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.defaults import NODE_DEFAULTS as D
from framework.messages import MessageKey
from framework.messages import text as message_text

from .base import Host, Port, StrictModel
from .installation import remote_path, service_identifier


class PanelAccess(StrictModel):
    mode: Literal["disabled", "basic_auth", "ip_allowlist"] = "disabled"
    username: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_.@-]{1,64}$")
    password_hash: str | None = Field(
        default=None, pattern=r"^\$2[aby]\$(?:1[0-6])\$[./A-Za-z0-9]{53}$"
    )
    allowed_ips: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("allowed_ips")
    @classmethod
    def networks(cls, value):
        result = []
        for item in value:
            network = ipaddress.ip_network(item, strict=False)
            if network.prefixlen == 0:
                raise ValueError(message_text(MessageKey.PANEL_ACCESS_INVALID))
            result.append(str(network))
        return list(dict.fromkeys(result))

    @model_validator(mode="after")
    def credentials(self):
        if self.mode == "basic_auth":
            valid = self.username and self.password_hash and not self.allowed_ips
        elif self.mode == "ip_allowlist":
            valid = self.allowed_ips and not self.username and not self.password_hash
        else:
            valid = not self.username and not self.password_hash and not self.allowed_ips
        if not valid:
            raise ValueError(message_text(MessageKey.PANEL_ACCESS_INVALID))
        return self


class Caddy(StrictModel):
    panel_access: PanelAccess = Field(default_factory=PanelAccess)
    service: str = D.caddy_service
    _service = field_validator("service")(service_identifier)
    config_path: str | None = None
    _config_path = field_validator("config_path")(remote_path)
    enabled: bool = False
    image: str = D.caddy_image
    domain: Host = D.caddy_domain
    https_port: Port = D.caddy_https_port

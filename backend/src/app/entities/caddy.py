from pydantic import field_validator

from app.defaults import NODE_DEFAULTS as D

from .base import Host, Port, StrictModel
from .installation import remote_path, service_identifier


class Caddy(StrictModel):
    service: str = D.caddy_service
    _service = field_validator("service")(service_identifier)
    config_path: str | None = None
    _config_path = field_validator("config_path")(remote_path)
    enabled: bool = False
    image: str = D.caddy_image
    domain: Host = D.caddy_domain
    https_port: Port = D.caddy_https_port

from app.defaults import NODE_DEFAULTS as D

from .base import Host, Port, StrictModel


class Caddy(StrictModel):
    enabled: bool = False
    image: str = D.caddy_image
    domain: Host = D.caddy_domain
    https_port: Port = D.caddy_https_port

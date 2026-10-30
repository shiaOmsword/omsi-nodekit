import re

from pydantic import Field, model_validator

from app.defaults import NODE_DEFAULTS as D

from .base import Slug, StrictModel
from .caddy import Caddy
from .panel import Panel
from .probe import Probe
from .ssh import SSH
from .tunnel import Tunnel


class Node(StrictModel):
    id: Slug
    name: str = Field(min_length=1, max_length=80)
    ssh: SSH
    panel: Panel = Field(default_factory=Panel)
    caddy: Caddy = Field(default_factory=Caddy)
    tunnels: list[Tunnel] = Field(default_factory=list)
    probe: Probe | None = None

    @model_validator(mode="after")
    def no_collisions(self):
        names = [t.name for t in self.tunnels]
        if len(names) != len(set(names)):
            raise ValueError("Tunnel names must be unique")
        ports = [self.panel.port, self.panel.subscription_port]
        ports += [t.local_port for t in self.tunnels]
        if self.caddy.enabled:
            ports += [D.acme_http_port, self.caddy.https_port]
        if len(ports) != len(set(ports)) or D.xray_port in ports:
            raise ValueError(f"Ports must be unique; port {D.xray_port} is reserved for Xray")
        for image in (self.panel.image, self.caddy.image):
            if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9./_:@-]+", image):
                raise ValueError("Invalid Docker image reference")
            last = image.rsplit("/", 1)[-1]
            if ":" not in last or last.endswith(":latest"):
                raise ValueError("Pin Docker images to a version or digest; latest is not accepted")
        return self

import re

from pydantic import Field, model_validator

from app.defaults import NODE_DEFAULTS as D
from framework.messages import MessageKey
from framework.messages import text as message_text

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
        if self.panel.installation != "managed":
            return self
        names = [t.name for t in self.tunnels]
        if len(names) != len(set(names)):
            raise ValueError(message_text(MessageKey.TUNNEL_NAMES_DUPLICATE))
        ports = [self.panel.port, self.panel.subscription_port]
        ports += [t.local_port for t in self.tunnels]
        if self.caddy.enabled:
            ports += [D.acme_http_port, self.caddy.https_port]
        if len(ports) != len(set(ports)) or D.xray_port in ports:
            raise ValueError(message_text(MessageKey.PORTS_CONFLICT, port=D.xray_port))
        for image in (self.panel.image, self.caddy.image):
            if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9./_:@-]+", image):
                raise ValueError(message_text(MessageKey.DOCKER_IMAGE_INVALID))
            last = image.rsplit("/", 1)[-1]
            if ":" not in last or last.endswith(":latest"):
                raise ValueError(message_text(MessageKey.DOCKER_IMAGE_UNPINNED))
        return self

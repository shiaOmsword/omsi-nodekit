import re

from pydantic import Field, model_validator

from app.defaults import NODE_DEFAULTS as D
from framework.messages import MessageKey
from framework.messages import text as message_text

from .base import Slug, StrictModel
from .caddy import Caddy
from .deployment import DeploymentTarget
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
    deployment: DeploymentTarget | None = None

    def export_config(self):
        """Portable node settings; elevation credentials belong only to the local SSH session."""
        return self.model_dump(mode="json", exclude={"ssh": {"sudo_password", "sudo_password_env"}})

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
        if self.deployment:
            ports += [i.port for i in self.deployment.inbounds]
            if self.deployment.caddy_mode == "existing" and self.caddy.enabled:
                ports.remove(D.acme_http_port)
            if self.caddy.enabled != (self.deployment.caddy_mode != "none"):
                raise ValueError(message_text(MessageKey.DEPLOYMENT_CADDY_MISMATCH))
            if self.deployment.inbounds and self.panel.image != D.panel_image:
                raise ValueError(message_text(MessageKey.DEPLOYMENT_API_VERSION))
        if len(ports) != len(set(ports)) or (not self.deployment and D.xray_port in ports):
            raise ValueError(message_text(MessageKey.PORTS_CONFLICT, port=D.xray_port))
        for image in (self.panel.image, self.caddy.image):
            if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9./_:@-]+", image):
                raise ValueError(message_text(MessageKey.DOCKER_IMAGE_INVALID))
            last = image.rsplit("/", 1)[-1]
            if ":" not in last or last.endswith(":latest"):
                raise ValueError(message_text(MessageKey.DOCKER_IMAGE_UNPINNED))
        return self

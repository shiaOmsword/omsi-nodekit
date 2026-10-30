from app.entities import (
    StrictModel, 
    Field,
    Slug,
    Panel,
    Caddy,
    Tunnel,
    Probe,
    SSH,
    model_validator,
    re,
    yaml,
)

class Node(StrictModel):
    id: Slug
    name: str = Field(min_length=1, max_length=80)
    ssh: SSH
    panel: Panel = Field(default_factory=Panel)
    caddy: Caddy = Field(default_factory=Caddy)
    tunnels: list[Tunnel] = Field(default_factory=list, max_length=12)
    probe: Probe | None = None

    @model_validator(mode="after")
    def no_collisions(self):
        names = [t.name for t in self.tunnels]
        if len(names) != len(set(names)):
            raise ValueError("Tunnel names must be unique")
        ports = [self.panel.port, self.panel.subscription_port]
        ports += [t.local_port for t in self.tunnels]
        if self.caddy.enabled:
            ports += [80, self.caddy.https_port]
        if len(ports) != len(set(ports)) or 443 in ports:
            raise ValueError("Ports must be unique; port 443 is reserved for Xray")
        for image in (self.panel.image, self.caddy.image):
            if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9./_:@-]+", image):
                raise ValueError("Invalid Docker image reference")
            last = image.rsplit("/", 1)[-1]
            if ":" not in last or last.endswith(":latest"):
                raise ValueError("Pin Docker images to a version or digest; latest is not accepted")
        return self

def parse_node(text: str) -> Node:
    if len(text.encode()) > 65536:
        raise ValueError("Configuration exceeds 64 KiB")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("YAML must contain an object")
    return Node.model_validate(data)
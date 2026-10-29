import re
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Port = Annotated[int, Field(ge=1, le=65535)]
Slug = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,39}$")]
Host = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9.-]{0,252}$")]
User = Annotated[str, Field(pattern=r"^[a-z_][a-z0-9_-]{0,31}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SSH(StrictModel):
    host: Host
    user: User = "root"
    port: Port = 22
    identity_file: str = "~/.ssh/id_ed25519"
    known_hosts_file: str = "~/.ssh/known_hosts"
    sudo: bool = False


class Panel(StrictModel):
    image: str = "ghcr.io/mhsanaei/3x-ui:3.11.0"
    port: Port = 2053
    base_path: str = "/nodekit/"
    subscription_port: Port = 2097
    subscription_path: str = "/sub/"

    @field_validator("base_path", "subscription_path")
    @classmethod
    def safe_url_path(cls, value: str) -> str:
        if not re.fullmatch(r"/(?:[a-zA-Z0-9_-]+/)*", value):
            raise ValueError("Use a path such as /nodekit/ or /sub/")
        return value


class Caddy(StrictModel):
    enabled: bool = False
    image: str = "caddy:2.10.2-alpine"
    domain: Host = "vpn.example.com"
    https_port: Port = 2096


class Tunnel(StrictModel):
    name: Slug
    host: Host
    user: User = "omsi"
    ssh_port: Port = 22
    local_port: Port = 15443
    target_port: Port = 443
    identity_file: str = "/home/omsi/.ssh/gb_xray_tunnel"
    known_hosts_file: str = "/home/omsi/.ssh/known_hosts"

    @field_validator("identity_file", "known_hosts_file")
    @classmethod
    def remote_path(cls, value: str) -> str:
        if not re.fullmatch(r"/(?:[a-zA-Z0-9_.-]+/)*[a-zA-Z0-9_.-]+", value):
            raise ValueError("Remote key paths must be absolute without spaces or expansions")
        if ".." in value.split("/"):
            raise ValueError("Parent path components are not allowed")
        return value


class Probe(StrictModel):
    socks_port: Port = 10808
    url: str = "https://www.cloudflare.com/cdn-cgi/trace"

    @field_validator("url")
    @classmethod
    def https_url(cls, value: str) -> str:
        if not re.fullmatch(r"https://[a-zA-Z0-9.-]+(?::[0-9]+)?/[^\s]*", value):
            raise ValueError("Probe URL must be an HTTPS URL without credentials")
        return value


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


class ConfigRequest(StrictModel):
    yaml: str


class JobRequest(StrictModel):
    action: Literal["check", "doctor", "fresh", "restore", "backup"]
    backup_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    revision: str

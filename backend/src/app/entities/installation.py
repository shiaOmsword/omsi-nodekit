import re
from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator

from framework.entities import Entity
from framework.messages import MessageKey
from framework.messages import text as message_text


class Installation(StrEnum):
    MANAGED = "managed"
    AUTO = "auto"
    NATIVE = "native"
    DOCKER = "docker"


def service_identifier(value):
    if value is not None and not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", value):
        raise ValueError(message_text(MessageKey.SIMPLE_NAME_REQUIRED))
    return value


def remote_path(value: str | None):
    if value is not None and (
        not value.startswith("/")
        or ".." in value.split("/")
        or any(ord(c) < 32 for c in value)
        or len(value) > 1024
    ):
        raise ValueError(message_text(MessageKey.ABSOLUTE_PATH_REQUIRED))
    return value


class CertificateFinding(Entity):
    usage: str
    cert_path: str
    key_path: str
    state: Literal[
        "not_configured", "missing", "unknown", "invalid", "expired", "not_yet_valid", "valid"
    ]
    key_readable: bool | None = None
    not_before: str | None = None
    not_after: str | None = None
    sha256: str | None = None


class ClientFinding(Entity):
    email: str
    enabled: bool
    has_subscription: bool = False


class InboundFinding(Entity):
    id: int
    remark: str
    protocol: str
    listen: str
    port: int
    enabled: bool
    network: str = ""
    security: str = ""
    client_count: int = 0
    clients: list[ClientFinding] = Field(default_factory=list)
    tag: str = ""
    server_names: list[str] = Field(default_factory=list)
    target: str = ""
    fingerprint: str = ""
    nodekit_name: str | None = None


class EndpointCheck(Entity):
    name: str
    state: Literal["ok", "error", "warning", "not_checked"]
    detail: str


class PanelFinding(Entity):
    id: str
    installation: str
    active: bool
    service: str | None = None
    container: str | None = None
    image: str | None = None
    database_path: str | None = None
    settings: dict[str, str] = Field(default_factory=dict)
    defaulted_settings: list[str] = Field(default_factory=list)
    certificates: list[CertificateFinding] = Field(default_factory=list)
    network_mode: str | None = None
    networks: list[str] = Field(default_factory=list)
    published_ports: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    inbounds: list[InboundFinding] = Field(default_factory=list)
    inbounds_readable: bool = False
    inbounds_truncated: bool = False


class ProxyRoute(Entity):
    listen: list[str] = Field(default_factory=list)
    hosts: list[str] = Field(default_factory=list)
    paths: list[str] = Field(default_factory=list)
    upstreams: list[str] = Field(default_factory=list)


class CaddyFinding(Entity):
    id: str
    installation: str
    active: bool
    service: str | None = None
    container: str | None = None
    image: str | None = None
    config_path: str | None = None
    config_source: str = "unavailable"
    network_mode: str | None = None
    networks: list[str] = Field(default_factory=list)
    published_ports: list[str] = Field(default_factory=list)
    host_gateway: str | None = None
    routes: list[ProxyRoute] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    compose_project: str | None = None
    compose_service: str | None = None
    compose_files: list[str] = Field(default_factory=list)
    compose_working_dir: str | None = None
    bridge_networks: list[dict] = Field(default_factory=list)


class FirewallFinding(Entity):
    state: Literal["active", "inactive", "unavailable", "unknown"] = "unknown"
    default_incoming: str | None = None
    default_outgoing: str | None = None
    default_routed: str | None = None
    rules: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DeploymentProfileFinding(Entity):
    panel_runtime: Literal["native", "docker"]
    caddy_runtime: Literal["none", "native", "docker"]
    required: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    ready: bool


class InstallationReport(Entity):
    observed_at: str
    ssh_host: str | None = None
    ssh_port: int | None = None
    panels: list[PanelFinding] = Field(default_factory=list)
    selected_panel: str | None = None
    caddy: list[CaddyFinding] = Field(default_factory=list)
    capabilities: dict[str, bool] = Field(default_factory=dict)
    profiles: list[DeploymentProfileFinding] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    subscription_checks: list[EndpointCheck] = Field(default_factory=list)
    subscription_url_template: str | None = None
    firewall: FirewallFinding | None = None
    network_checks: list[EndpointCheck] = Field(default_factory=list)
    egress: dict | None = None
    traffic_checks: list[EndpointCheck] = Field(default_factory=list)


class KeySelection(Entity):
    key_id: str | None
    yaml: str

    @field_validator("key_id")
    @classmethod
    def key_id_format(cls, value):
        return validate_key_id(value) if value is not None else value


class InstallationSelection(Entity):
    yaml: str
    installation: Installation


def validate_key_id(value):
    if not re.fullmatch(r"[a-f0-9]{32}", value):
        raise ValueError(message_text(MessageKey.SSH_KEY_ID_INVALID))
    return value

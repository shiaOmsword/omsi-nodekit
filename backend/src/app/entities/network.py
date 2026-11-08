import ipaddress
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from framework.messages import MessageKey
from framework.messages import text as message_text

from .base import Host, Port, Slug, StrictModel


class InboundChange(StrictModel):
    id: int = Field(gt=0)
    expected_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    operation: Literal["update", "delete", "add_client", "delete_client"] = "update"
    remark: str | None = Field(default=None, min_length=1, max_length=120)
    port: Port | None = None
    server_name: Host | None = None
    client_email: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.@-]{0,79}$")
    close_unmanaged_rule: bool = False
    wg_domain: Host | None = None
    wg_mtu: int | None = Field(default=None, ge=576, le=1500)
    wg_dns: str | None = Field(default=None, max_length=120, pattern=r"^[0-9a-fA-F:., ]*$")

    @field_validator("remark")
    @classmethod
    def printable(cls, value):
        if value is not None and any(ord(c) < 32 for c in value):
            raise ValueError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
        return value

    @model_validator(mode="after")
    def changes(self):
        if self.operation == "delete" and any(
            x is not None
            for x in (
                self.remark,
                self.port,
                self.server_name,
                self.wg_domain,
                self.wg_mtu,
                self.wg_dns,
            )
        ):
            raise ValueError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
        if self.operation == "update" and all(
            x is None
            for x in (
                self.remark,
                self.port,
                self.server_name,
                self.wg_domain,
                self.wg_mtu,
                self.wg_dns,
            )
        ):
            raise ValueError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
        if self.operation in {"update", "delete"} and self.client_email is not None:
            raise ValueError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
        if self.operation in {"add_client", "delete_client"} and (
            not self.client_email
            or any(
                x is not None
                for x in (
                    self.remark,
                    self.port,
                    self.server_name,
                    self.wg_domain,
                    self.wg_mtu,
                    self.wg_dns,
                )
            )
            or self.close_unmanaged_rule
        ):
            raise ValueError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
        return self


class TrafficRequest(StrictModel):
    id: int = Field(gt=0)
    expected_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class TunnelRequest(TrafficRequest):
    name: Slug
    outbound_tag: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_.-]+$")
    members: list[Slug] = Field(default_factory=list, max_length=6)
    pool_name: Slug | None = None

    @model_validator(mode="after")
    def pool_arguments(self):
        if self.members and (
            len(self.members) < 2
            or len(self.members) != len(set(self.members))
            or self.name != self.members[0]
            or self.pool_name is None
        ):
            raise ValueError(message_text(MessageKey.TUNNEL_CONFIG_INVALID))
        if not self.members and self.pool_name is not None:
            raise ValueError(message_text(MessageKey.TUNNEL_CONFIG_INVALID))
        return self


class TunnelRouteRequest(StrictModel):
    kind: Literal["tunnel", "pool"]
    name: Slug
    expected_exit_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    inbounds: list[TrafficRequest] = Field(min_length=1, max_length=100)

    @field_validator("inbounds")
    @classmethod
    def unique_inbounds(cls, value):
        if len({i.id for i in value}) != len(value):
            raise ValueError(message_text(MessageKey.TUNNEL_ROUTE_INVALID))
        return value


class XHTTPChange(StrictModel):
    """Managed XHTTP ingress. Private backend binds only to the Caddy host gateway."""

    operation: Literal["create", "update", "publish"] = "create"
    id: int | None = Field(default=None, gt=0)
    expected_fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    remark: str = Field(min_length=1, max_length=120)
    domain: Host
    port: Port
    path: str = Field(pattern=r"^/[a-zA-Z0-9_-]{1,64}/$")
    mode: Literal["auto", "packet-up", "stream-up"] = "auto"
    client_email: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.@-]{0,79}$")

    @model_validator(mode="after")
    def validate_change(self):
        if (
            (self.operation == "create" and (self.id is not None or self.expected_fingerprint))
            or (
                self.operation == "update"
                and (not self.id or not self.expected_fingerprint or self.client_email)
            )
            or ("." not in self.domain or ".." in self.domain)
        ):
            raise ValueError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
        if self.operation == "publish" and (
            not self.id or not self.expected_fingerprint or self.client_email
        ):
            raise ValueError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
        if any(ord(c) < 32 for c in self.remark):
            raise ValueError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
        return self


class BackupClientImport(StrictModel):
    include_external_links: bool = True
    source_inbound_id: int = Field(gt=0)
    target_inbound_id: int = Field(gt=0)
    expected_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    client_refs: list[str] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def valid_refs(self):
        if len(set(self.client_refs)) != len(self.client_refs) or any(
            re.fullmatch(r"(?:n:[1-9][0-9]{0,12}|l:[0-9]{1,6})", item) is None
            for item in self.client_refs
        ):
            raise ValueError(message_text(MessageKey.BACKUP_CLIENTS_INVALID))
        return self


class SubscriptionMaintenance(StrictModel):
    """Server-side checks or an explicitly acknowledged managed panel restart."""

    id: int = Field(gt=0)
    expected_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    mode: Literal["audit", "clear_server_cache"] = "audit"
    client_email: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.@-]{0,79}$")
    acknowledge_restart: bool = False

    @model_validator(mode="after")
    def valid_maintenance(self):
        if (self.mode == "clear_server_cache") != self.acknowledge_restart:
            raise ValueError(message_text(MessageKey.SUB_CACHE_REQUEST_INVALID))
        return self


class TCPTuningRequest(StrictModel):
    algorithm: Literal["cubic", "bbr"]
    expected_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class WireGuardChange(StrictModel):
    operation: Literal["create", "restore"] = "create"
    remark: str = Field(min_length=1, max_length=120, pattern=r"^[^\x00-\x1f]+$")
    domain: Host
    port: Port = 51820
    mtu: int = Field(default=1420, ge=576, le=1500)
    dns: str = Field(default="1.1.1.1", max_length=120)
    subnet: str = "10.77.0.0/24"
    client_email: str = Field(default="client-wg", pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.@-]{0,79}$")
    source_inbound_id: int | None = Field(default=None, gt=0)
    source_ipv6: bool | None = None

    @model_validator(mode="after")
    def valid_wireguard(self):
        if (self.operation == "restore") != (self.source_inbound_id is not None):
            raise ValueError(message_text(MessageKey.WIREGUARD_BACKUP_INVALID))
        if self.operation != "restore" and self.source_ipv6 is not None:
            raise ValueError(message_text(MessageKey.WIREGUARD_BACKUP_INVALID))
        network = ipaddress.ip_network(self.subnet)
        if network.version != 4 or not 16 <= network.prefixlen <= 29:
            raise ValueError(message_text(MessageKey.WIREGUARD_BACKUP_INVALID))
        for value in self.dns.split(","):
            ipaddress.ip_address(value.strip())
        return self


class SystemRestoreRequest(StrictModel):
    expected_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class NetworkBenchmarkRequest(StrictModel):
    url: str = Field(min_length=10, max_length=400)
    attempts: int = Field(default=3, ge=1, le=3)
    sample_bytes: int = Field(default=16 * 1024 * 1024, ge=1024 * 1024, le=32 * 1024 * 1024)
    min_mbps: float = Field(default=100, gt=0, le=100000, allow_inf_nan=False)
    max_rtt_ms: float = Field(default=100, gt=0, le=10000, allow_inf_nan=False)
    max_jitter_ms: float = Field(default=20, ge=0, le=10000, allow_inf_nan=False)
    max_loss_percent: float = Field(default=1, ge=0, le=100, allow_inf_nan=False)

    @field_validator("url")
    @classmethod
    def safe_url(cls, value):
        try:
            url = urlsplit(value)
            if (
                url.scheme != "https"
                or not url.hostname
                or url.username
                or url.password
                or url.fragment
                or any(ord(c) <= 32 or ord(c) > 126 for c in value)
                or (url.port is not None and not 1 <= url.port <= 65535)
            ):
                raise ValueError()
        except ValueError as exc:
            raise ValueError(message_text(MessageKey.NETWORK_BENCHMARK_INVALID)) from exc
        return value


class TunnelRestartRequest(StrictModel):
    names: list[Slug] = Field(min_length=1)

    @field_validator("names")
    @classmethod
    def unique_names(cls, value):
        if len(value) != len(set(value)):
            raise ValueError(message_text(MessageKey.TUNNEL_RESTART_REQUEST_INVALID))
        return value


class TunnelControlRequest(TunnelRestartRequest):
    operation: Literal["enable", "disable"]


class TunnelSetupRequest(TunnelRestartRequest):
    expected_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    outbound_tag: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_.-]+$")
    balancer_tag: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_.-]{1,120}$")
    fallback_tag: str = Field(default="direct", pattern=r"^[a-zA-Z0-9_.-]{1,120}$")

    @field_validator("names")
    @classmethod
    def limit_names(cls, value):
        if len(value) > 6:
            raise ValueError(message_text(MessageKey.TUNNEL_CONFIG_INVALID))
        return value


class BalancerChange(StrictModel):
    operation: Literal["balancer"]
    expected_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    tag: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,120}$")
    members: list[str] = Field(min_length=1, max_length=100)
    fallback_tag: str = Field(default="direct", pattern=r"^[a-zA-Z0-9_.-]{1,120}$")

    @field_validator("members")
    @classmethod
    def valid_members(cls, value):
        if len(set(value)) != len(value) or any(
            re.fullmatch(r"[a-zA-Z0-9_.-]{1,120}", tag) is None for tag in value
        ):
            raise ValueError(message_text(MessageKey.XRAY_CONFIG_INVALID))
        return value


class RouteChange(StrictModel):
    operation: Literal["route"]
    expected_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    balancer_tag: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,120}$")
    rule_index: int | None = Field(default=None, ge=0, lt=100)
    inbounds: list[TrafficRequest] = Field(min_length=1, max_length=100)

    @field_validator("inbounds")
    @classmethod
    def unique_inbounds(cls, value):
        if len({i.id for i in value}) != len(value):
            raise ValueError(message_text(MessageKey.XRAY_CONFIG_INVALID))
        return value

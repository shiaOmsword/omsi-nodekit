import os
import re
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.defaults import DISCOVERY_DEFAULTS as DISCOVERY
from framework.entities import Entity
from framework.messages import MessageKey
from framework.messages import text as message_text

BASE_DIR = Path(__file__).resolve().parents[2]


class ServerSettings(Entity):
    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    frontend_dev_port: int = Field(default=5173, ge=1, le=65535)
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "::1")
    allowed_origins: tuple[str, ...] = ()

    @field_validator("host")
    @classmethod
    def loopback(cls, value):
        if value not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError(message_text(MessageKey.LOOPBACK_REQUIRED))
        return value

    def origins(self) -> set[str]:
        return (
            set(self.allowed_origins)
            | {
                f"http://{host}:{port}"
                for host in self.allowed_hosts
                for port in (self.port, self.frontend_dev_port)
            }
            | {f"http://[::1]:{port}" for port in (self.port, self.frontend_dev_port)}
        )


class Limits(Entity):
    config_bytes: int = Field(default=65536, ge=1024, le=1024 * 1024)
    backup_bytes: int = Field(default=64 * 1024 * 1024, ge=1024)
    filename_length: int = Field(default=100, ge=16, le=255)
    event_length: int = Field(default=5000, ge=100)
    job_history: int = Field(default=50, ge=1, le=1000)
    max_tunnels: int = Field(default=12, ge=0, le=100)


class SSHSettings(Entity):
    binary: str = "ssh"
    connect_timeout: int = Field(default=10, ge=1)
    alive_interval: int = Field(default=10, ge=1)
    alive_count: int = Field(default=3, ge=1)
    operation_timeout: int = Field(default=1200, ge=1)
    keygen_binary: str = "ssh-keygen"
    keygen_timeout: int = Field(default=30, ge=1)
    python_command: str = "python3 -"
    sudo_python_command: str = "sudo -n python3 -"


class DiscoverySettings(Entity):
    panel_defaults: dict[str, str] = Field(
        default_factory=lambda: dict(DISCOVERY["panel_defaults"])
    )
    native_database: str = DISCOVERY["native_database"]
    native_binary: str = DISCOVERY["native_binary"]
    native_environment_files: tuple[str, ...] = DISCOVERY["native_environment_files"]
    container_database: str = DISCOVERY["container_database"]
    caddy_config: str = DISCOVERY["caddy_config"]
    metadata_bytes: int = Field(default=DISCOVERY["metadata_bytes"], ge=1024, le=8 * 1024 * 1024)
    max_containers: int = Field(default=DISCOVERY["max_containers"], ge=1, le=500)
    max_routes: int = Field(default=DISCOVERY["max_routes"], ge=1, le=500)


class DeploymentSettings(Entity):
    remote_root: str = "/opt/omsi-nodekit"
    remote_ssh_binary: str = "/usr/bin/ssh"
    unit_directory: str = "/etc/systemd/system"
    systemd_directory: str = "/run/systemd/system"
    lock_file: str = "/run/lock/omsi-nodekit.lock"
    service_prefix: str = "omsi"
    command_timeout: int = Field(default=120, ge=1)
    pull_timeout: int = Field(default=600, ge=1)
    startup_timeout: int = Field(default=180, ge=1)
    readiness_attempts: int = Field(default=30, ge=1)
    readiness_interval: float = Field(default=1, gt=0)
    socket_timeout: int = Field(default=2, ge=1)
    http_timeout: int = Field(default=8, ge=1)
    probe_timeout: int = Field(default=20, ge=1)
    docker_log_size: str = "10m"
    docker_log_files: int = Field(default=3, ge=1)
    timezone: str = "UTC"
    panel_username: str = "omsi"
    password_bytes: int = Field(default=28, ge=24)
    tunnel_restart_seconds: int = Field(default=3, ge=1)

    @field_validator(
        "remote_root", "remote_ssh_binary", "unit_directory", "systemd_directory", "lock_file"
    )
    @classmethod
    def absolute_safe_path(cls, value):
        if not re.fullmatch(r"/(?:[a-zA-Z0-9_.-]+/)*[a-zA-Z0-9_.-]+", value):
            raise ValueError(message_text(MessageKey.ABSOLUTE_PATH_REQUIRED))
        if ".." in value.split("/"):
            raise ValueError(message_text(MessageKey.PARENT_PATH_FORBIDDEN))
        return value

    @field_validator("service_prefix")
    @classmethod
    def simple_name(cls, value):
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", value):
            raise ValueError(message_text(MessageKey.SIMPLE_NAME_REQUIRED))
        return value


class Settings(BaseSettings):
    environment: str = "local"
    data_dir: Path = BASE_DIR / "data"
    frontend_dir: Path = BASE_DIR.parent / "frontend" / "dist"
    template_file: Path = BASE_DIR / "config" / "config-example.yaml"
    database_name: str = "nodekit.db"
    backups_directory: str = "backups"
    keys_directory: str = "ssh-keys"
    sqlite_timeout: float = Field(default=10, gt=0)
    worker_count: int = Field(default=1, ge=1)
    log_level: str = "INFO"
    server: ServerSettings = Field(default_factory=ServerSettings)
    limits: Limits = Field(default_factory=Limits)
    ssh: SSHSettings = Field(default_factory=SSHSettings)
    deployment: DeploymentSettings = Field(default_factory=DeploymentSettings)
    discovery: DiscoverySettings = Field(default_factory=DiscoverySettings)
    model_config = SettingsConfigDict(
        env_prefix="NODEKIT_",
        env_nested_delimiter="__",
        env_file=BASE_DIR / ".envs" / ".local.env",
        extra="forbid",
    )

    @field_validator("database_name", "backups_directory", "keys_directory")
    @classmethod
    def local_name(cls, value):
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", value):
            raise ValueError(message_text(MessageKey.LOCAL_NAME_REQUIRED))
        return value


@lru_cache
def get_settings() -> Settings:
    environment = os.getenv("NODEKIT_ENVIRONMENT", "local")
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", environment):
        raise ValueError(message_text(MessageKey.INVALID_ENVIRONMENT))
    return Settings(_env_file=BASE_DIR / ".envs" / f".{environment}.env")

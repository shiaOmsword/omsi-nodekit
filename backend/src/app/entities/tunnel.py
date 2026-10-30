import re

from pydantic import field_validator

from app.defaults import NODE_DEFAULTS as D
from framework.messages import MessageKey
from framework.messages import text as message_text

from .base import Host, Port, Slug, StrictModel, User


class Tunnel(StrictModel):
    name: Slug
    host: Host
    user: User = D.tunnel_user
    ssh_port: Port = D.ssh_port
    local_port: Port = D.tunnel_local_port
    target_port: Port = D.xray_port
    identity_file: str = D.tunnel_identity_file
    known_hosts_file: str = D.tunnel_known_hosts

    @field_validator("identity_file", "known_hosts_file")
    @classmethod
    def remote_path(cls, value: str) -> str:
        if not re.fullmatch(r"/(?:[a-zA-Z0-9_.-]+/)*[a-zA-Z0-9_.-]+", value):
            raise ValueError(message_text(MessageKey.REMOTE_KEY_PATH_INVALID))
        if ".." in value.split("/"):
            raise ValueError(message_text(MessageKey.PARENT_PATH_FORBIDDEN))
        return value

from pydantic import field_validator

from app.defaults import NODE_DEFAULTS as D

from .base import Host, Port, StrictModel, User
from .installation import validate_key_id


class SSH(StrictModel):
    key_id: str | None = None

    @field_validator("key_id")
    @classmethod
    def key_id_format(cls, value):
        return validate_key_id(value) if value is not None else value

    host: Host
    user: User = D.ssh_user
    port: Port = D.ssh_port
    identity_file: str = D.ssh_identity_file
    known_hosts_file: str = D.ssh_known_hosts
    sudo: bool = False

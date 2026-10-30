from app.defaults import NODE_DEFAULTS as D

from .base import Host, Port, StrictModel, User


class SSH(StrictModel):
    host: Host
    user: User = D.ssh_user
    port: Port = D.ssh_port
    identity_file: str = D.ssh_identity_file
    known_hosts_file: str = D.ssh_known_hosts
    sudo: bool = False

from app.entities import Slug, Host, User, Port, StrictModel, field_validator, re

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
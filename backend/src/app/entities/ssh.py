from app.entities import Host, User, Port, StrictModel

class SSH(StrictModel):
    host: Host
    user: User = "root"
    port: Port = 22
    identity_file: str = "~/.ssh/id_ed25519"
    known_hosts_file: str = "~/.ssh/known_hosts"
    sudo: bool = False
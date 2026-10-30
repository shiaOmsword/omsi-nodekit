from app.entities import Port, StrictModel, Host

class Caddy(StrictModel):
    enabled: bool = False
    image: str = "caddy:2.10.2-alpine"
    domain: Host = "vpn.example.com"
    https_port: Port = 2096

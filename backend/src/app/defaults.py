"""Domain defaults: node YAML may override these values explicitly."""

from dataclasses import dataclass


@dataclass(frozen=True)
class NodeDefaults:
    panel_image: str = "ghcr.io/mhsanaei/3x-ui:3.11.0"
    panel_port: int = 2053
    panel_path: str = "/nodekit/"
    subscription_port: int = 2097
    subscription_path: str = "/sub/"
    caddy_image: str = "caddy:2.10.2-alpine"
    caddy_domain: str = "vpn.example.com"
    caddy_https_port: int = 2096
    acme_http_port: int = 80
    xray_port: int = 443
    ssh_user: str = "root"
    ssh_port: int = 22
    ssh_identity_file: str = "~/.ssh/id_ed25519"
    ssh_known_hosts: str = "~/.ssh/known_hosts"
    tunnel_user: str = "omsi"
    tunnel_local_port: int = 15443
    tunnel_identity_file: str = "/home/omsi/.ssh/gb_xray_tunnel"
    tunnel_known_hosts: str = "/home/omsi/.ssh/known_hosts"
    probe_socks_port: int = 10808
    probe_url: str = "https://www.cloudflare.com/cdn-cgi/trace"


NODE_DEFAULTS = NodeDefaults()
APP_TITLE = "OMSI Nodekit"
APP_VERSION = "0.1.0"

XUI_TABLES = ("settings", "inbounds", "users")
XUI_SETTINGS_COLUMNS = {"settings": ("key", "value")}
XUI_LEGACY_PANEL_PATH = "/"
XUI_DATABASE_FILE = "x-ui.db"

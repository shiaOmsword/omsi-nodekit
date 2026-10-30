"""Domain defaults: node YAML may override these values explicitly."""

from dataclasses import dataclass


@dataclass(frozen=True)
class NodeDefaults:
    panel_service: str = "x-ui"
    caddy_service: str = "caddy"
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

# Upstream settings may omit rows whose values still use these conventional defaults.
XUI_READ_DEFAULTS = {
    "webListen": "",
    "webPort": "2053",
    "webBasePath": "/",
    "webDomain": "",
    "webCertFile": "",
    "webKeyFile": "",
    "subListen": "",
    "subPort": "2096",
    "subPath": "/sub/",
    "subDomain": "",
    "subCertFile": "",
    "subKeyFile": "",
    "subEnable": "true",
}

# Default locations are shared with the stdlib-only remote agent.
DISCOVERY_DEFAULTS = {
    "panel_defaults": XUI_READ_DEFAULTS,
    "native_database": "/etc/x-ui/x-ui.db",
    "native_binary": "/usr/local/x-ui/x-ui",
    "native_environment_files": ("/etc/default/x-ui", "/etc/conf.d/x-ui", "/etc/sysconfig/x-ui"),
    "container_database": "/etc/x-ui/x-ui.db",
    "caddy_config": "/etc/caddy/Caddyfile",
    "metadata_bytes": 1024 * 1024,
    "max_containers": 100,
    "max_routes": 100,
}

# Official v3.11.0 release asset digests, verified through GitHub Releases.
NATIVE_RELEASE = {
    "version": "3.11.0",
    "repository": "https://github.com/MHSanaei/3x-ui/releases/download/v3.11.0",
    "sha256": {
        "amd64": "0ddfa4702f595442e2962acd81addc768fdacaa4ff2672c971a0463dae744916",
        "arm64": "f50b4c30fd919d018f2f4c3d8db53a4ca027503d581328727770afb116a79d90",
    },
    "archive_bytes": 160 * 1024 * 1024,
    "unpacked_bytes": 512 * 1024 * 1024,
}

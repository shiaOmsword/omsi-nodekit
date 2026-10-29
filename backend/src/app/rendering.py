import yaml

from app.entities.node import Node


def remote_dir(node: Node) -> str:
    return f"/opt/omsi-nodekit/{node.id}"


def compose_config(node: Node) -> str:
    base = remote_dir(node)
    services = {
        "panel": {
            "image": node.panel.image,
            "network_mode": "host",
            "restart": "unless-stopped",
            "environment": {"XUI_ENABLE_FAIL2BAN": "false", "TZ": "UTC"},
            "volumes": [f"{base}/db:/etc/x-ui", f"{base}/cert:/root/cert"],
            "logging": {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}},
        }
    }
    if node.caddy.enabled:
        services["caddy"] = {
            "image": node.caddy.image,
            "network_mode": "host",
            "restart": "unless-stopped",
            "volumes": [
                f"{base}/Caddyfile:/etc/caddy/Caddyfile:ro",
                f"{base}/caddy-data:/data",
                f"{base}/caddy-config:/config",
            ],
        }
    return yaml.safe_dump({"name": f"omsi-{node.id}", "services": services}, sort_keys=False)


def caddyfile(node: Node) -> str:
    return f"""{{
    admin off
}}

https://{node.caddy.domain}:{node.caddy.https_port} {{
    tls {{
        issuer acme {{
            disable_tlsalpn_challenge
        }}
    }}
    @subscriptions path {node.panel.subscription_path}*
    handle @subscriptions {{
        reverse_proxy 127.0.0.1:{node.panel.subscription_port}
    }}
    handle {{
        respond 404
    }}
}}
"""


def tunnel_unit(node: Node, index: int) -> str:
    tunnel = node.tunnels[index]
    return f"""[Unit]
Description=OMSI {node.id} tunnel {tunnel.name}
Wants=network-online.target
After=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
User={tunnel.user}
ExecStart=/usr/bin/ssh -N -T -p {tunnel.ssh_port} -i {tunnel.identity_file} -o UserKnownHostsFile={tunnel.known_hosts_file} -o StrictHostKeyChecking=yes -o IdentitiesOnly=yes -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=10 -o ServerAliveCountMax=3 -o ConnectTimeout=10 -o ControlMaster=no -o Compression=no -L 127.0.0.1:{tunnel.local_port}:127.0.0.1:{tunnel.target_port} {tunnel.user}@{tunnel.host}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""


def artifacts(node: Node) -> dict[str, str]:
    files = {"compose.yaml": compose_config(node)}
    if node.caddy.enabled:
        files["Caddyfile"] = caddyfile(node)
    for index, tunnel in enumerate(node.tunnels):
        files[f"omsi-{node.id}-{tunnel.name}.service"] = tunnel_unit(node, index)
    return files


def plan(node: Node, action: str) -> dict:
    steps = ["SSH connection with strict host-key verification", "Check Docker Compose and systemd"]
    if action in {"fresh", "restore"}:
        steps += ["Refuse unmanaged or existing installations", "Pull pinned Docker images"]
        steps += [
            "Initialize private panel credentials"
            if action == "fresh"
            else "Validate and restore SQLite snapshot"
        ]
        steps += [
            "Bind panel and subscription backend to localhost",
            "Install configured SSH tunnel units",
            "Start services and verify HTTP endpoints",
        ]
    elif action == "backup":
        steps += [
            "Create consistent SQLite snapshot",
            "Download snapshot and configuration manifest",
        ]
    elif action == "doctor":
        steps += [
            "Check panel HTTP and subscription listener",
            "Check tunnel units and local ports",
        ]
        steps += [
            "Send HTTPS request through configured SOCKS proxy"
            if node.probe
            else "End-to-end proxy probe: not configured"
        ]
    return {
        "action": action,
        "remote_dir": remote_dir(node),
        "steps": steps,
        "files": artifacts(node),
    }

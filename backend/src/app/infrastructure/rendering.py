from app.config import DeploymentSettings, SSHSettings
from app.entities import Node
from app.ports import ArtifactRenderer
from framework.entities import ValidationError, YamlCodec
from framework.messages import MessageKey
from framework.messages import text as message_text


class NodeArtifacts(ArtifactRenderer):
    def __init__(self, policy: DeploymentSettings, ssh: SSHSettings, yaml_codec: YamlCodec):
        self.policy = policy
        self.ssh = ssh
        self.yaml = yaml_codec

    def remote_dir(self, node: Node) -> str:
        return f"{self.policy.remote_root}/{node.id}"

    def compose_config(self, node: Node) -> str:
        base = self.remote_dir(node)
        services = {
            "panel": {
                "image": node.panel.image,
                "network_mode": "host",
                "restart": "unless-stopped",
                "environment": {"XUI_ENABLE_FAIL2BAN": "false", "TZ": self.policy.timezone},
                "volumes": [f"{base}/db:/etc/x-ui", f"{base}/cert:/root/cert"],
                "logging": {
                    "driver": "json-file",
                    "options": {
                        "max-size": self.policy.docker_log_size,
                        "max-file": str(self.policy.docker_log_files),
                    },
                },
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
        return self.yaml.dumps(
            {"name": f"{self.policy.service_prefix}-{node.id}", "services": services}
        )

    def caddyfile(self, node: Node) -> str:
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

    def tunnel_unit(self, node: Node, index: int) -> str:
        tunnel = node.tunnels[index]
        return f"""[Unit]
Description=OMSI {node.id} tunnel {tunnel.name}
Wants=network-online.target
After=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
User={tunnel.user}
ExecStart={self.policy.remote_ssh_binary} -N -T -p {tunnel.ssh_port} -i {tunnel.identity_file} -o UserKnownHostsFile={tunnel.known_hosts_file} -o StrictHostKeyChecking=yes -o IdentitiesOnly=yes -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval={self.ssh.alive_interval} -o ServerAliveCountMax={self.ssh.alive_count} -o ConnectTimeout={self.ssh.connect_timeout} -o ControlMaster=no -o Compression=no -L 127.0.0.1:{tunnel.local_port}:127.0.0.1:{tunnel.target_port} {tunnel.user}@{tunnel.host}
Restart=always
RestartSec={self.policy.tunnel_restart_seconds}

[Install]
WantedBy=multi-user.target
"""

    def artifacts(self, node: Node) -> dict[str, str]:
        if node.panel.installation != "managed":
            return {}
        files = {"compose.yaml": self.compose_config(node)}
        if node.caddy.enabled:
            files["Caddyfile"] = self.caddyfile(node)
        for index, tunnel in enumerate(node.tunnels):
            files[f"{self.policy.service_prefix}-{node.id}-{tunnel.name}.service"] = (
                self.tunnel_unit(node, index)
            )
        return files

    def plan(self, node: Node, action: str) -> dict:
        if action in {"fresh", "restore"} and node.panel.installation != "managed":
            raise ValidationError(message_text(MessageKey.EXISTING_READ_ONLY))
        steps = [
            message_text(MessageKey.PLAN_SSH_CHECK),
            message_text(MessageKey.PLAN_DISCOVERY),
        ]
        if action in {"fresh", "restore"}:
            steps += [
                message_text(MessageKey.PLAN_EXISTING_GUARD),
                message_text(MessageKey.PLAN_IMAGES_PULL),
            ]
            steps += [
                message_text(MessageKey.PLAN_CREDENTIALS_CREATE)
                if action == "fresh"
                else message_text(MessageKey.PLAN_DATABASE_RESTORE)
            ]
            steps += [
                message_text(MessageKey.PLAN_LISTENERS_CONFIGURE),
                message_text(MessageKey.PLAN_TUNNELS_INSTALL),
                message_text(MessageKey.PLAN_SERVICES_VERIFY),
            ]
        elif action == "backup":
            steps += [
                message_text(MessageKey.PLAN_EXISTING_BACKUP),
                message_text(MessageKey.PLAN_SNAPSHOT_CREATE),
                message_text(MessageKey.PLAN_SNAPSHOT_DOWNLOAD),
            ]
        elif action == "doctor":
            steps += [
                message_text(MessageKey.PLAN_EXISTING_DIAGNOSTICS),
                message_text(MessageKey.PLAN_TUNNELS_CHECK),
            ]
            steps += [
                message_text(MessageKey.PLAN_PROXY_CHECK)
                if node.probe
                else message_text(MessageKey.PLAN_PROXY_NOT_CONFIGURED)
            ]
        if action not in {"fresh", "restore"}:
            steps.append(message_text(MessageKey.PLAN_READ_ONLY))
        return {
            "action": action,
            "remote_dir": self.remote_dir(node),
            "steps": steps,
            "files": self.artifacts(node) if action in {"fresh", "restore"} else {},
        }

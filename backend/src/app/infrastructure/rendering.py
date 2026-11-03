import json

from app.agent.caddy_config import standalone_config, subscription_site
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
        if node.deployment and node.deployment.panel_runtime == "native":
            services.pop("panel")
        if node.caddy.enabled and (not node.deployment or node.deployment.caddy_mode == "docker"):
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
        data = node.export_config()
        if node.deployment and node.deployment.caddy_mode == "existing":
            return subscription_site(data)
        return standalone_config(data)

    def panel_unit(self, node: Node) -> str:
        base = self.remote_dir(node)
        return f"""[Unit]
Description=Nodekit {node.id} native 3x-ui
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
WorkingDirectory={base}/runtime
Environment=XUI_DB_TYPE=sqlite XUI_DB_FOLDER={base}/db XUI_BIN_FOLDER={base}/runtime/bin XUI_LOG_FOLDER={base}/logs XUI_ENABLE_FAIL2BAN=false TZ={self.policy.timezone}
ExecStart={base}/runtime/x-ui
Restart=on-failure
RestartSec=3
UMask=0077

[Install]
WantedBy=multi-user.target
"""

    def tunnel_unit(self, node: Node, index: int) -> str:
        tunnel = node.tunnels[index]
        host_key_checking = "accept-new" if tunnel.host_key_policy == "accept-new" else "yes"
        return f"""[Unit]
Description=OMSI {node.id} tunnel {tunnel.name}
Wants=network-online.target
After=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
User={tunnel.user}
ExecStart={self.policy.remote_ssh_binary} -F none -N -T -p {tunnel.ssh_port} -i {tunnel.identity_file} -o UserKnownHostsFile={tunnel.known_hosts_file} -o StrictHostKeyChecking={host_key_checking} -o IdentitiesOnly=yes -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval={self.ssh.alive_interval} -o ServerAliveCountMax={self.ssh.alive_count} -o ConnectTimeout={self.ssh.connect_timeout} -o ControlMaster=no -o Compression=no -L 127.0.0.1:{tunnel.local_port}:127.0.0.1:{tunnel.target_port} {tunnel.user}@{tunnel.host}
Restart=always
RestartSec={self.policy.tunnel_restart_seconds}

[Install]
WantedBy=multi-user.target
"""

    def artifacts(self, node: Node) -> dict[str, str]:
        if node.panel.installation != "managed":
            return {}
        files = {"compose.yaml": self.compose_config(node)}
        if node.deployment:
            files["deployment.json"] = json.dumps(node.deployment.model_dump(mode="json"), indent=2)
        if node.deployment and node.deployment.panel_runtime == "native":
            files[f"{self.policy.service_prefix}-{node.id}-panel.service"] = self.panel_unit(node)
            if node.deployment.caddy_mode != "docker":
                files.pop("compose.yaml")
        if node.caddy.enabled:
            name = (
                "Caddyfile.site"
                if node.deployment and node.deployment.caddy_mode == "existing"
                else "Caddyfile"
            )
            files[name] = self.caddyfile(node)
        for index, tunnel in enumerate(node.tunnels):
            files[f"{self.policy.service_prefix}-{node.id}-{tunnel.name}.service"] = (
                self.tunnel_unit(node, index)
            )
        return files

    def plan(self, node: Node, action: str) -> dict:
        if action in {"fresh", "restore"} and node.panel.installation != "managed":
            raise ValidationError(message_text(MessageKey.EXISTING_READ_ONLY))
        if action in {"configure", "attach_caddy"} and (
            node.panel.installation != "managed"
            or not node.deployment
            or node.deployment.caddy_mode != "existing"
        ):
            raise ValidationError(message_text(MessageKey.SUBSCRIPTION_CONFIGURE_GUARD))
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
            if node.deployment:
                target = node.deployment
                steps.insert(
                    2,
                    message_text(
                        MessageKey.DEPLOYMENT_NATIVE_PLAN
                        if target.panel_runtime == "native"
                        else MessageKey.DEPLOYMENT_DOCKER_PLAN
                    ),
                )
                if target.install_docker:
                    steps.insert(3, message_text(MessageKey.DEPLOYMENT_DOCKER_PLAN))
                if target.caddy_mode == "existing":
                    steps.append(message_text(MessageKey.DEPLOYMENT_CADDY_PLAN))
                if action == "fresh" and target.inbounds:
                    steps.append(message_text(MessageKey.DEPLOYMENT_INBOUNDS_PLAN))
                if target.panel_runtime == "native" and target.caddy_mode != "docker":
                    steps.remove(message_text(MessageKey.PLAN_IMAGES_PULL))
        elif action == "attach_caddy":
            steps.append(message_text(MessageKey.CADDY_ATTACH_PLAN))
        elif action == "configure":
            steps.append(message_text(MessageKey.SUBSCRIPTION_CONFIGURE_PLAN))
        elif action == "inbound":
            steps.append(message_text(MessageKey.INBOUND_PLAN))
        elif action == "client_import":
            steps.append(message_text(MessageKey.CLIENT_IMPORT_PLAN))
            steps.append(message_text(MessageKey.CLIENT_EXTERNAL_PLAN))
        elif action == "subscription_maintenance":
            steps.append(message_text(MessageKey.SUB_CACHE_AUDIT_PLAN))
        elif action == "wireguard":
            steps.append(message_text(MessageKey.WIREGUARD_PLAN))
        elif action == "xhttp":
            steps.append(message_text(MessageKey.XHTTP_APPLY_PLAN))
        elif action == "tunnel":
            steps.append(message_text(MessageKey.TUNNEL_APPLY_PLAN))
        elif action == "tcp_tuning":
            steps.append(message_text(MessageKey.TCP_TUNING_PLAN))
        elif action == "traffic":
            steps.append(message_text(MessageKey.TRAFFIC_PLAN))
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
        if action in {
            "fresh",
            "restore",
            "configure",
            "attach_caddy",
            "inbound",
            "xhttp",
            "wireguard",
        } and (not node.deployment or node.deployment.manage_ufw):
            steps.append(message_text(MessageKey.NETWORK_UFW_PLAN))
        if (
            action in {"fresh", "restore", "configure", "attach_caddy"}
            and node.deployment
            and node.deployment.manage_caddy_ports
            and node.deployment.caddy_mode == "existing"
        ):
            steps.append(message_text(MessageKey.NETWORK_COMPOSE_PLAN))
        if action not in {
            "fresh",
            "restore",
            "configure",
            "attach_caddy",
            "inbound",
            "tunnel",
            "xhttp",
            "wireguard",
            "client_import",
            "subscription_maintenance",
            "tcp_tuning",
        }:
            steps.append(message_text(MessageKey.PLAN_READ_ONLY))
        return {
            "action": action,
            "remote_dir": self.remote_dir(node),
            "steps": steps,
            "files": (
                {
                    k: v
                    for k, v in self.artifacts(node).items()
                    if action not in {"configure", "attach_caddy"}
                    or k in {"Caddyfile.site", "deployment.json"}
                }
                if action in {"fresh", "restore", "configure", "attach_caddy"}
                else {}
            ),
        }

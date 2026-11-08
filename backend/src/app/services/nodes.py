import json

from app.entities import JobAction, NodeFactory, NodeState, StoredNode
from app.ports import ArtifactRenderer, NodeRepository, NodeTemplate
from framework.entities import ConflictError, ValidationError, YamlCodec
from framework.messages import MessageKey
from framework.messages import text as message_text

from .backups import BackupService
from .keys import SSHKeyService


class NodeService:
    def __init__(
        self,
        nodes: NodeRepository,
        factory: NodeFactory,
        renderer: ArtifactRenderer,
        template: NodeTemplate,
        keys: SSHKeyService,
        yaml_codec: YamlCodec,
        backups: BackupService,
    ):
        self.nodes = nodes
        self.factory = factory
        self.renderer = renderer
        self.templates = template
        self.keys = keys
        self.yaml = yaml_codec
        self.backups = backups

    def template(self):
        return {"yaml": self.templates.read()}

    def validate(self, text: str):
        node = self.factory.from_yaml(text)
        return {"node": node.model_dump(mode="json"), "files": self.renderer.artifacts(node)}

    def save(self, node_id: str, text: str):
        node = self.factory.from_yaml(text)
        if node.ssh.key_id:
            self.keys.require(node.ssh.key_id)
        if node.id != node_id:
            raise ValidationError(message_text(MessageKey.NODE_ID_MISMATCH))
        return self.nodes.save(StoredNode.create(node, text))

    def set_state(self, node_id: str, state: NodeState):
        return self.nodes.set_state(node_id, state)

    def delete(self, node_id: str):
        self.nodes.delete(node_id)
        return {"deleted": True, "remote_untouched": True}

    def get(self, node_id):
        return self.nodes.get(node_id)

    def list(self):
        return self.nodes.list()

    def preview(self, node_id: str, action: JobAction):
        if action in {
            JobAction.INBOUND,
            JobAction.TRAFFIC,
            JobAction.SYSTEM_RESTORE,
            JobAction.NETWORK_BENCHMARK,
            JobAction.TCP_TUNING,
            JobAction.TUNNEL_SETUP,
            JobAction.TUNNEL_CONTROL,
            JobAction.XRAY,
            JobAction.TUNNEL,
            JobAction.TUNNEL_RESTART,
            JobAction.TUNNEL_ROUTE,
            JobAction.XHTTP,
            JobAction.WIREGUARD,
            JobAction.CLIENT_IMPORT,
            JobAction.SUBSCRIPTION_MAINTENANCE,
        }:
            raise ValidationError(message_text(MessageKey.INBOUND_REQUEST_INVALID))
        stored = self.nodes.get(node_id)
        return {
            **self.renderer.plan(self.factory.from_yaml(stored.yaml), action),
            "revision": stored.revision,
        }

    def preview_operation(self, node_id, request):
        stored = self.nodes.get(node_id)
        if stored.revision != request.revision:
            raise ConflictError(message_text(MessageKey.CONFIGURATION_CHANGED))
        if request.action == JobAction.RESTORE:
            if not request.backup_id:
                raise ValidationError(message_text(MessageKey.RESTORE_BACKUP_REQUIRED))
            node = self.factory.from_yaml(stored.yaml)
            self.backups.check_restore(node, request.backup_id)
            plan = self.preview(node_id, request.action)
            plan["steps"].append(
                message_text(
                    MessageKey.RESTORE_ENV_PLAN,
                    runtime=node.deployment.panel_runtime if node.deployment else "docker",
                    caddy=node.deployment.caddy_mode
                    if node.deployment
                    else ("docker" if node.caddy.enabled else "none"),
                )
            )
            return plan
        if request.action not in {
            JobAction.INBOUND,
            JobAction.TRAFFIC,
            JobAction.SYSTEM_RESTORE,
            JobAction.NETWORK_BENCHMARK,
            JobAction.TUNNEL_SETUP,
            JobAction.TUNNEL_CONTROL,
            JobAction.XRAY,
            JobAction.TUNNEL,
            JobAction.TUNNEL_RESTART,
            JobAction.TUNNEL_ROUTE,
            JobAction.XHTTP,
            JobAction.WIREGUARD,
            JobAction.CLIENT_IMPORT,
            JobAction.SUBSCRIPTION_MAINTENANCE,
            JobAction.TCP_TUNING,
        }:
            return self.preview(node_id, request.action)
        options = request.model_dump(
            mode="json", exclude={"action", "revision", "backup_id"}, exclude_none=True
        )
        node = self.factory.from_yaml(stored.yaml)
        if node.panel.installation != "managed" and request.action not in {
            JobAction.TCP_TUNING,
            JobAction.SYSTEM_RESTORE,
            JobAction.NETWORK_BENCHMARK,
        }:
            raise ValidationError(
                message_text(
                    MessageKey.TUNNEL_RESTART_REQUEST_INVALID
                    if request.action == JobAction.TUNNEL_RESTART
                    else MessageKey.INBOUND_MANAGED_REQUIRED
                )
            )
        if request.action in {JobAction.TUNNEL_SETUP, JobAction.TUNNEL_CONTROL}:
            names = (request.tunnel_setup or request.tunnel_control).names
            if not set(names) <= {t.name for t in node.tunnels}:
                raise ValidationError(message_text(MessageKey.TUNNEL_CONFIG_INVALID))
        if request.action == JobAction.TUNNEL_RESTART:
            available = {t.name for t in node.tunnels}
            if not set(request.tunnel_restart.names) <= available:
                raise ValidationError(message_text(MessageKey.TUNNEL_RESTART_REQUEST_INVALID))
        if request.action == JobAction.TUNNEL:
            available = {t.name for t in node.tunnels}
            if request.tunnel.name not in available or not set(request.tunnel.members) <= available:
                raise ValidationError(message_text(MessageKey.TUNNEL_CONFIG_INVALID))
        plan = self.renderer.plan(node, request.action)
        if request.action == JobAction.WIREGUARD and request.wireguard.operation == "restore":
            source = self.backups.wireguard_source(
                request.backup_id,
                request.wireguard.source_inbound_id,
                request.wireguard.source_ipv6,
            )
            plan["steps"].append(
                message_text(
                    MessageKey.WIREGUARD_SOURCE_PLAN,
                    name=source["remark"],
                    count=source["client_count"],
                )
            )
            if source.get("source_format") == "wg-easy-v15":
                old = source["endpoint"]
                plan["steps"].append(
                    message_text(
                        MessageKey.WG_EASY_ENDPOINT_PLAN,
                        old_host=old["host"],
                        old_port=old["port"],
                        host=request.wireguard.domain,
                        port=request.wireguard.port,
                    )
                )
                plan["steps"].append(message_text(MessageKey.WG_EASY_ROUTING_PLAN))
        if request.action == JobAction.TUNNEL_ROUTE:
            route = request.tunnel_route
            if route.kind == "tunnel" and route.name not in {t.name for t in node.tunnels}:
                raise ValidationError(message_text(MessageKey.TUNNEL_ROUTE_INVALID))
            plan["steps"].append(
                message_text(
                    MessageKey.TUNNEL_ROUTE_SELECTION,
                    name=route.name,
                    ids=", ".join(str(i.id) for i in route.inbounds),
                )
            )
        if request.action == JobAction.TUNNEL_RESTART:
            plan["steps"].append(
                message_text(
                    MessageKey.TUNNEL_RESTART_SELECTION,
                    names=", ".join(request.tunnel_restart.names),
                )
            )
        if request.action == JobAction.SYSTEM_RESTORE:
            summary = self.backups.system_summary(request.backup_id)
            if summary["node_id"] != node.id:
                raise ValidationError(message_text(MessageKey.SYSTEM_BACKUP_CONFLICT))
            plan["steps"].append(
                message_text(
                    MessageKey.SYSTEM_BACKUP_CONTENTS,
                    algorithm=summary["tcp_algorithm"],
                    tunnels=", ".join(summary["tunnel_names"]),
                )
            )
        if (
            request.action == JobAction.SUBSCRIPTION_MAINTENANCE
            and request.subscription_maintenance.mode == "clear_server_cache"
        ):
            plan["steps"].append(message_text(MessageKey.SUB_CACHE_RESTART_PLAN))
        return {
            **plan,
            "revision": stored.revision,
            "options": options,
            "files": {"operation.json": json.dumps(options, ensure_ascii=False, indent=2)},
        }

    def select_key(self, text, key_id):
        self.factory.from_yaml(text)
        if key_id:
            self.keys.require(key_id)
        document = self.yaml.loads(text)
        if key_id:
            document["ssh"]["key_id"] = key_id
        else:
            document["ssh"].pop("key_id", None)
        updated = self.yaml.dumps(document)
        self.factory.from_yaml(updated)
        return {"yaml": updated}

    def select_installation(self, text, installation):
        self.factory.from_yaml(text)
        document = self.yaml.loads(text)
        document.setdefault("panel", {})["installation"] = str(installation)
        updated = self.yaml.dumps(document)
        self.factory.from_yaml(updated)
        return {"yaml": updated}

    def select_deployment(self, text, target):
        self.factory.from_yaml(text)
        document = self.yaml.loads(text)
        document.setdefault("panel", {}).update(
            installation="managed", container=None, database_path=None
        )
        document["deployment"] = target.model_dump(mode="json")
        document.setdefault("caddy", {})["enabled"] = target.caddy_mode != "none"
        updated = self.yaml.dumps(document)
        self.factory.from_yaml(updated)
        return {"yaml": updated}

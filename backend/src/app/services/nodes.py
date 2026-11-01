import json

from app.entities import JobAction, NodeFactory, NodeState, StoredNode
from app.ports import ArtifactRenderer, NodeRepository, NodeTemplate
from framework.entities import ConflictError, ValidationError, YamlCodec
from framework.messages import MessageKey
from framework.messages import text as message_text

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
    ):
        self.nodes = nodes
        self.factory = factory
        self.renderer = renderer
        self.templates = template
        self.keys = keys
        self.yaml = yaml_codec

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
        if action in {JobAction.INBOUND, JobAction.TRAFFIC, JobAction.TUNNEL, JobAction.XHTTP}:
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
        if request.action not in {
            JobAction.INBOUND,
            JobAction.TRAFFIC,
            JobAction.TUNNEL,
            JobAction.XHTTP,
        }:
            return self.preview(node_id, request.action)
        options = request.model_dump(
            mode="json", exclude={"action", "revision", "backup_id"}, exclude_none=True
        )
        node = self.factory.from_yaml(stored.yaml)
        if node.panel.installation != "managed":
            raise ValidationError(message_text(MessageKey.INBOUND_MANAGED_REQUIRED))
        if request.action == JobAction.TUNNEL:
            available = {t.name for t in node.tunnels}
            if request.tunnel.name not in available or not set(request.tunnel.members) <= available:
                raise ValidationError(message_text(MessageKey.TUNNEL_CONFIG_INVALID))
        plan = self.renderer.plan(node, request.action)
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

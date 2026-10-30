from app.entities import JobAction, NodeFactory, StoredNode
from app.ports import ArtifactRenderer, NodeRepository, NodeTemplate
from framework.entities import ValidationError


class NodeService:
    def __init__(
        self,
        nodes: NodeRepository,
        factory: NodeFactory,
        renderer: ArtifactRenderer,
        template: NodeTemplate,
    ):
        self.nodes = nodes
        self.factory = factory
        self.renderer = renderer
        self.templates = template

    def template(self):
        return {"yaml": self.templates.read()}

    def validate(self, text: str):
        node = self.factory.from_yaml(text)
        return {"node": node.model_dump(mode="json"), "files": self.renderer.artifacts(node)}

    def save(self, node_id: str, text: str):
        node = self.factory.from_yaml(text)
        if node.id != node_id:
            raise ValidationError("URL node ID must match YAML id")
        return self.nodes.save(StoredNode.create(node, text))

    def get(self, node_id):
        return self.nodes.get(node_id)

    def list(self):
        return self.nodes.list()

    def preview(self, node_id: str, action: JobAction):
        stored = self.nodes.get(node_id)
        return {
            **self.renderer.plan(self.factory.from_yaml(stored.yaml), action),
            "revision": stored.revision,
        }

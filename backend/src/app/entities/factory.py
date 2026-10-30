from app.config import Limits
from framework.entities import EntityFactory, ValidationError

from .node import Node


class NodeFactory:
    def __init__(self, entities: EntityFactory, limits: Limits):
        self.entities = entities
        self.limits = limits

    def from_yaml(self, text: str) -> Node:
        if len(text.encode()) > self.limits.config_bytes:
            raise ValidationError(f"Configuration exceeds {self.limits.config_bytes} bytes")
        node = self.entities.from_yaml(Node, text)
        if len(node.tunnels) > self.limits.max_tunnels:
            raise ValidationError(f"Maximum tunnel count is {self.limits.max_tunnels}")
        return node

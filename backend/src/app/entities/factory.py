from app.config import Limits
from framework.entities import EntityFactory, ValidationError
from framework.messages import MessageKey
from framework.messages import text as message_text

from .node import Node


class NodeFactory:
    def __init__(self, entities: EntityFactory, limits: Limits):
        self.entities = entities
        self.limits = limits

    def from_yaml(self, text: str) -> Node:
        if len(text.encode()) > self.limits.config_bytes:
            raise ValidationError(
                message_text(MessageKey.CONFIGURATION_TOO_LARGE, limit=self.limits.config_bytes)
            )
        node = self.entities.from_yaml(Node, text)
        if len(node.tunnels) > self.limits.max_tunnels:
            raise ValidationError(
                message_text(MessageKey.TUNNEL_LIMIT_EXCEEDED, limit=self.limits.max_tunnels)
            )
        return node

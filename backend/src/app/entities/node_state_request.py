from app.entities.records import NodeState

from .base import StrictModel


class NodeStateRequest(StrictModel):
    state: NodeState

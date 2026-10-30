from .base import StrictModel


class ConfigRequest(StrictModel):
    yaml: str

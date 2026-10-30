import re

from pydantic import field_validator

from app.defaults import NODE_DEFAULTS as D
from framework.messages import MessageKey
from framework.messages import text as message_text

from .base import Port, StrictModel
from .installation import Installation, remote_path, service_identifier


class Panel(StrictModel):
    installation: Installation = Installation.MANAGED
    database_path: str | None = None
    container: str | None = None
    service: str = D.panel_service

    _database_path = field_validator("database_path")(remote_path)

    _identifier = field_validator("container", "service")(service_identifier)

    image: str = D.panel_image
    port: Port = D.panel_port
    base_path: str = D.panel_path
    subscription_port: Port = D.subscription_port
    subscription_path: str = D.subscription_path

    @field_validator("base_path", "subscription_path")
    @classmethod
    def safe_url_path(cls, value: str) -> str:
        if not re.fullmatch(r"/(?:[a-zA-Z0-9_-]+/)*", value):
            raise ValueError(message_text(MessageKey.URL_PATH_INVALID))
        return value

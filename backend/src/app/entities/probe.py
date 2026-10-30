import re

from pydantic import field_validator

from app.defaults import NODE_DEFAULTS as D
from framework.messages import MessageKey
from framework.messages import text as message_text

from .base import Port, StrictModel


class Probe(StrictModel):
    socks_port: Port = D.probe_socks_port
    url: str = D.probe_url

    @field_validator("url")
    @classmethod
    def https_url(cls, value: str) -> str:
        if not re.fullmatch(r"https://[a-zA-Z0-9.-]+(?::[0-9]+)?/[^\s]*", value):
            raise ValueError(message_text(MessageKey.PROBE_URL_INVALID))
        return value

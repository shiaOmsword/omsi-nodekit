from collections.abc import Mapping
from string import Formatter
from types import MappingProxyType

from .codes import MessageKey
from .definitions import MESSAGES


class MessageCatalog:
    """Immutable templates. A bad key or a missing/extra parameter fails immediately."""

    def __init__(self, templates: Mapping[MessageKey, str] | None = None):
        self.templates = MappingProxyType(dict(MESSAGES if templates is None else templates))

    def render(self, key: MessageKey, **params) -> str:
        key = MessageKey(key)
        template = self.templates[key]
        expected = {field for _, field, _, _ in Formatter().parse(template) if field is not None}
        if set(params) != expected:
            raise ValueError(key.value, tuple(sorted(expected)), tuple(sorted(params)))
        return template.format(**params)


DEFAULT_CATALOG = MessageCatalog()


def text(key: MessageKey, **params) -> str:
    return DEFAULT_CATALOG.render(key, **params)

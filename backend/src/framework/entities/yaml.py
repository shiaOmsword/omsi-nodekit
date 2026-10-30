from typing import Any

import yaml

from framework.messages import MessageKey
from framework.messages import text as message_text

from .exception import ValidationError


class YamlCodec:
    def loads(self, text: str) -> Any:
        try:
            return yaml.safe_load(text)
        except (yaml.YAMLError, RecursionError) as exc:
            # Parser diagnostics can include the original configuration / secrets.
            raise ValidationError(message_text(MessageKey.YAML_INVALID)) from exc

    def dumps(self, data: Any) -> str:
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)

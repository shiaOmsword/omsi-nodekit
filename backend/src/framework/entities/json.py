import json
from typing import Any


class JsonCodec:
    def loads(self, text: str) -> Any:
        return json.loads(text)

    def dumps(self, data: Any, *, pretty: bool = False) -> str:
        return json.dumps(data, ensure_ascii=False, indent=2 if pretty else None)

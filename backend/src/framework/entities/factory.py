from collections.abc import Mapping
from typing import TypeVar

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from .exception import ValidationError
from .json import JsonCodec
from .yaml import YamlCodec

Model = TypeVar("Model", bound=BaseModel)


class EntityFactory:
    """Reusable validated construction, without a registry of application entities."""

    def __init__(self, yaml_codec: YamlCodec, json_codec: JsonCodec):
        self.yaml = yaml_codec
        self.json = json_codec

    def create(self, model: type[Model], data: Mapping | None = None, **fields) -> Model:
        try:
            return model.model_validate({**(data or {}), **fields})
        except PydanticValidationError as exc:
            details = [
                {"field": ".".join(map(str, item["loc"])), "code": item["type"]}
                for item in exc.errors(include_input=False, include_context=False)
            ]
            raise ValidationError("Entity validation failed", details=details) from exc

    def from_yaml(self, model: type[Model], text: str) -> Model:
        data = self.yaml.loads(text)
        if not isinstance(data, dict):
            raise ValidationError("YAML must contain an object")
        return self.create(model, data)

    def from_json(self, model: type[Model], text: str) -> Model:
        try:
            data = self.json.loads(text)
        except (ValueError, RecursionError) as exc:
            raise ValidationError("Invalid JSON document") from exc
        if not isinstance(data, dict):
            raise ValidationError("JSON must contain an object")
        return self.create(model, data)

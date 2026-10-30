from pydantic import BaseModel, ConfigDict


class Entity(BaseModel):
    """Shared value-object behaviour; persistence and HTTP do not belong here."""

    model_config = ConfigDict(extra="forbid", frozen=True)

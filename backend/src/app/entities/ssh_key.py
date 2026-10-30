from pydantic import Field, field_validator

from framework.entities import Entity
from framework.messages import MessageKey
from framework.messages import text as message_text
from framework.utils import new_id, utc_timestamp


class SSHKeyRequest(Entity):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def readable_name(cls, value):
        value = value.strip()
        if not value or any(ord(char) < 32 for char in value):
            raise ValueError(message_text(MessageKey.SSH_KEY_NAME_INVALID))
        return value


class SSHKey(Entity):
    id: str = Field(default_factory=new_id)
    name: str
    public_key: str
    fingerprint: str
    created_at: str = Field(default_factory=utc_timestamp)

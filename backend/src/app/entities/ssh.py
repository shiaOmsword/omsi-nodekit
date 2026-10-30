from pydantic import Field, SecretStr, field_validator, model_validator

from app.defaults import NODE_DEFAULTS as D
from framework.messages import MessageKey
from framework.messages import text as message_text
from framework.utils import is_single_line_secret

from .base import Host, Port, StrictModel, User
from .installation import validate_key_id


class SSH(StrictModel):
    key_id: str | None = None

    @field_validator("key_id")
    @classmethod
    def key_id_format(cls, value):
        return validate_key_id(value) if value is not None else value

    host: Host
    user: User = D.ssh_user
    port: Port = D.ssh_port
    identity_file: str = D.ssh_identity_file
    known_hosts_file: str = D.ssh_known_hosts
    sudo: bool = False
    sudo_password: SecretStr | None = Field(default=None, repr=False)
    sudo_password_env: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")

    @field_validator("sudo_password")
    @classmethod
    def valid_password(cls, value):
        if value is not None and not is_single_line_secret(value.get_secret_value()):
            raise ValueError(message_text(MessageKey.SUDO_PASSWORD_INVALID))
        return value

    @model_validator(mode="after")
    def password_source(self):
        if self.sudo_password is not None and self.sudo_password_env is not None:
            raise ValueError(message_text(MessageKey.SUDO_PASSWORD_AMBIGUOUS))
        if not self.sudo and (self.sudo_password is not None or self.sudo_password_env is not None):
            raise ValueError(message_text(MessageKey.SUDO_PASSWORD_REQUIRES_ENABLED))
        return self

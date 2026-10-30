from app.entities import SSH
from framework.entities import ConfigurationError
from framework.messages import MessageKey
from framework.messages import text as message_text
from framework.utils import EnvironmentSecrets, is_single_line_secret


class SudoPasswordResolver:
    def __init__(self, environment: EnvironmentSecrets):
        self.environment = environment

    def resolve(self, ssh: SSH) -> str | None:
        if ssh.sudo_password is not None:
            return ssh.sudo_password.get_secret_value()
        if ssh.sudo_password_env is None:
            return None
        value = self.environment.get(ssh.sudo_password_env)
        if value is None:
            raise ConfigurationError(
                message_text(MessageKey.SUDO_PASSWORD_ENV_MISSING, name=ssh.sudo_password_env)
            )
        if not is_single_line_secret(value):
            raise ConfigurationError(message_text(MessageKey.SUDO_PASSWORD_INVALID))
        return value

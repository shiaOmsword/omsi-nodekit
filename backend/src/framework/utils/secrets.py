import os

SECRET_MAX_LENGTH = 4096


def is_single_line_secret(value: str) -> bool:
    return 0 < len(value) <= SECRET_MAX_LENGTH and not any(c in value for c in "\r\n\0")


class EnvironmentSecrets:
    """Read from the backend process environment, without retaining a secret registry."""

    def get(self, name: str) -> str | None:
        return os.environ.get(name)

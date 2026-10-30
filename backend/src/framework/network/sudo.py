import base64
import secrets
import shlex

from framework.messages import MessageKey
from framework.messages import text as message_text
from framework.utils.secrets import is_single_line_secret

from .execute import ProcessError


class SudoInput:
    """Frame a password separately from source, including cached/NOPASSWD sudo."""

    DEFAULT_COMMAND = ("sudo", "-S", "-p", "", "--", "python3")

    def __init__(self, password: str):
        if not is_single_line_secret(password):
            raise ProcessError(message_text(MessageKey.SUDO_PASSWORD_INVALID))
        self._password = password
        self.marker = f"__NODEKIT_SUDO_{secrets.token_hex(24)}__"

    def command(self, command: tuple[str, ...]) -> str:
        # -c contains only this fixed decoder and a random marker, never the password/source.
        code = f"""import base64, json, sys
marker = {self.marker.encode()!r}
header = sys.stdin.buffer.readline()
if header.rstrip(b"\\r\\n") != marker:
    header = sys.stdin.buffer.readline()
if header.rstrip(b"\\r\\n") != marker:
    print(json.dumps({{"message": {message_text(MessageKey.SUDO_PROTOCOL_INVALID)!r}, "level": "error"}}), flush=True)
    raise SystemExit(1)
try:
    source = base64.b64decode(sys.stdin.buffer.read().strip(), validate=True).decode("utf-8")
    program = compile(source, "<nodekit-agent>", "exec")
except Exception:
    print(json.dumps({{"message": {message_text(MessageKey.SUDO_PROTOCOL_INVALID)!r}, "level": "error"}}), flush=True)
    raise SystemExit(1)
print(marker.decode(), flush=True)
exec(program, {{"__name__": "__main__"}})
"""
        return shlex.join((*command, "-c", code))

    def content(self, script: str) -> str:
        encoded = base64.b64encode(script.encode("utf-8")).decode("ascii")
        return f"{self._password}\n{self.marker}\n{encoded}\n"

    def authenticated(self, line: str) -> bool:
        return line.strip() == self.marker

    def redact(self, line: str) -> str:
        return line.replace(self._password, "[REDACTED]")

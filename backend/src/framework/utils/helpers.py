import hashlib
from datetime import datetime, timezone
from uuid import uuid4


def new_id() -> str:
    return uuid4().hex


def sha256(value: bytes | str) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

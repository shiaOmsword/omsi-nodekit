import base64
import json
import subprocess
import tempfile
import threading
from pathlib import Path

from app import remote_agent
from app.entities.node import Node
from app.rendering import artifacts
from app.storage import Store

MAX_BACKUP = 64 * 1024 * 1024


def validate_backup(raw: bytes):
    if not raw or len(raw) > MAX_BACKUP or not raw.startswith(b"SQLite format 3\x00"):
        raise ValueError("Upload a complete SQLite .db snapshot, maximum 64 MiB")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "snapshot.db"
        path.write_bytes(raw)
        try:
            remote_agent.validate_db(path)
        except Exception as exc:
            raise ValueError(f"Invalid 3x-ui snapshot: {exc}") from exc





def agent_source(node: Node, action: str, backup: bytes | None = None):
    payload = {"node": node.model_dump(), "action": action, "files": artifacts(node)}
    if backup is not None:
        validate_backup(backup)
        payload["backup"] = base64.b64encode(backup).decode()
    source = Path(remote_agent.__file__).read_text()
    return (
        source
        + "\ntry:\n    main(json.loads("
        + repr(json.dumps(payload))
        + "))\nexcept Exception as exc:\n    emit(str(exc), 'error')\n    raise SystemExit(1)\n"
    )



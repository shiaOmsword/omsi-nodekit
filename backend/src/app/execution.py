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


def ssh_command(node: Node):
    identity = Path(node.ssh.identity_file).expanduser().resolve()
    known_hosts = Path(node.ssh.known_hosts_file).expanduser().resolve()
    for path in (identity, known_hosts):
        if not path.is_file():
            raise ValueError(f"Local SSH file does not exist: {path}")
    return [
        "ssh",
        "-T",
        "-p",
        str(node.ssh.port),
        "-i",
        str(identity),
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "ServerAliveInterval=10",
        "-o",
        "ServerAliveCountMax=3",
        f"{node.ssh.user}@{node.ssh.host}",
        "sudo -n python3 -" if node.ssh.sudo else "python3 -",
    ]


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


def execute(store: Store, job_id: str, node: Node, action: str, backup_id: str | None):
    store.start(job_id)
    received_backup = None
    try:
        backup = store.backup_path(backup_id).read_bytes() if backup_id else None
        script = agent_source(node, action, backup)
        command = ssh_command(node)
        store.event(job_id, f"Connecting to {node.ssh.user}@{node.ssh.host}:{node.ssh.port}")
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        timed_out = threading.Event()

        def timeout():
            timed_out.set()
            process.kill()

        timer = threading.Timer(1200, timeout)
        timer.start()

        def send():
            try:
                process.stdin.write(script)
                process.stdin.close()
            except (BrokenPipeError, OSError):
                pass

        sender = threading.Thread(target=send, daemon=True)
        sender.start()
        try:
            for line in process.stdout:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    store.event(job_id, line.strip(), "warning")
                    continue
                if "backup" in event:
                    if action != "backup" or received_backup is not None:
                        raise RuntimeError("Unexpected backup payload")
                    raw = base64.b64decode(event["backup"], validate=True)
                    validate_backup(raw)
                    received_backup = store.add_backup(raw, f"{node.id}-x-ui.db")["id"]
                    store.save_manifest(received_backup, node)
                else:
                    store.event(job_id, str(event.get("message", "")), event.get("level", "info"))
            returncode = process.wait()
            sender.join(timeout=3)
            if timed_out.is_set():
                raise RuntimeError(
                    "SSH timed out after 20 minutes; inspect remote services before retrying"
                )
            if returncode:
                raise RuntimeError(
                    f"Remote operation failed (SSH exit {returncode}); see the journal"
                )
            if action == "backup" and not received_backup:
                raise RuntimeError("Remote operation returned no backup")
        finally:
            timer.cancel()
            if process.poll() is None:
                process.kill()
                process.wait()
        store.finish(job_id, "succeeded", backup_id=received_backup)
    except Exception as exc:
        store.event(job_id, str(exc), "error")
        store.finish(job_id, "failed", str(exc), backup_id=received_backup)

import base64
import sqlite3
import subprocess

import pytest

from app import remote_agent
from app.execution import agent_source, validate_backup
from app.rendering import artifacts
from tests.conftest import create_database


def test_snapshot_checks_integrity_and_preserves_clients(db_file, tmp_path):
    snapshot = tmp_path / "copy.db"
    remote_agent.snapshot(db_file, snapshot)
    validate_backup(snapshot.read_bytes())
    with sqlite3.connect(snapshot) as db:
        assert db.execute("SELECT settings,stream_settings FROM inbounds").fetchone() == (
            "client-uuid-and-sub-id",
            "reality-private-key",
        )


def test_live_wal_database_backup_is_consistent(tmp_path):
    source = create_database(tmp_path / "live.db")
    with sqlite3.connect(source) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("UPDATE inbounds SET settings='new-committed-client'")
        writer.commit()
        dest = tmp_path / "snapshot.db"
        remote_agent.snapshot(source, dest)
        with sqlite3.connect(dest) as db:
            assert (
                db.execute("SELECT settings FROM inbounds").fetchone()[0] == "new-committed-client"
            )


@pytest.mark.parametrize("raw", [b"", b"not sqlite", b"SQLite format 3\x00broken"])
def test_corrupt_backups_are_rejected(raw):
    with pytest.raises(ValueError):
        validate_backup(raw)


def test_unrelated_sqlite_file_rejected(tmp_path):
    path = tmp_path / "other.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE wrong (x)")
    with pytest.raises(ValueError, match="3x-ui"):
        validate_backup(path.read_bytes())


def test_listener_patch_preserves_identities_and_routing(node, db_file):
    remote_agent.patch_listeners(db_file, node.model_dump(), restoring=True)
    with sqlite3.connect(db_file) as db:
        settings = dict(db.execute("SELECT key,value FROM settings"))
        assert settings["webListen"] == settings["subListen"] == "127.0.0.1"
        assert settings["subPort"] == "2097"
        assert settings["xrayTemplateConfig"] == "original-outbound"
        assert db.execute("SELECT password FROM users").fetchone()[0] == "original-hash"
        assert (
            db.execute("SELECT stream_settings FROM inbounds").fetchone()[0]
            == "reality-private-key"
        )


def test_restore_refuses_subscription_path_change_atomically(node, db_file):
    data = node.model_dump()
    data["panel"]["subscription_path"] = "/different/"
    with pytest.raises(RuntimeError, match="subscription_path"):
        remote_agent.patch_listeners(db_file, data, restoring=True)
    with sqlite3.connect(db_file) as db:
        assert db.execute("SELECT value FROM settings WHERE key='webListen'").fetchone() is None


def test_deploy_refuses_existing_files_before_any_commands(node, tmp_path, monkeypatch):
    base = tmp_path / "node"
    base.mkdir()
    original = base / "important.db"
    original.write_bytes(b"do not delete")
    monkeypatch.setattr(
        remote_agent, "run", lambda *args, **kwargs: pytest.fail("No command should run")
    )
    with pytest.raises(RuntimeError, match="not empty"):
        remote_agent.deploy({"node": node.model_dump(), "action": "fresh"}, base)
    assert original.read_bytes() == b"do not delete"


def test_restore_to_new_directory_never_recreates_users(node, db_file, tmp_path, monkeypatch):
    base = tmp_path / "restored"
    calls = []
    monkeypatch.setattr(
        remote_agent.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 3, "", "")
    )
    monkeypatch.setattr(remote_agent, "run", lambda args, **kwargs: calls.append(args) or "")
    monkeypatch.setattr(remote_agent, "require_free", lambda port: None)
    monkeypatch.setattr(remote_agent, "port_open", lambda port: True)
    monkeypatch.setattr(remote_agent, "doctor", lambda *args: None)
    remote_agent.deploy(
        {
            "node": node.model_dump(),
            "action": "restore",
            "backup": base64.b64encode(db_file.read_bytes()).decode(),
            "files": artifacts(node),
        },
        base,
    )
    assert not any("setting" in call for call in calls)
    assert ["docker", "compose", "-f", str(base / "compose.yaml"), "up", "-d"] in calls
    with sqlite3.connect(base / "db/x-ui.db") as db:
        assert db.execute("SELECT username FROM users").fetchone()[0] == "original-admin"


def test_fresh_initializes_credentials_before_start(node, tmp_path, monkeypatch):
    base = tmp_path / "fresh"
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if "setting" in args:
            create_database(base / "db/x-ui.db")
        return ""

    monkeypatch.setattr(
        remote_agent.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 3, "", "")
    )
    monkeypatch.setattr(remote_agent, "run", fake_run)
    monkeypatch.setattr(remote_agent, "require_free", lambda port: None)
    monkeypatch.setattr(remote_agent, "port_open", lambda port: True)
    monkeypatch.setattr(remote_agent, "doctor", lambda *args: None)
    remote_agent.deploy(
        {"node": node.model_dump(), "action": "fresh", "files": artifacts(node)}, base
    )
    credential_call = next(i for i, c in enumerate(calls) if "setting" in c)
    start_call = next(i for i, c in enumerate(calls) if "up" in c)
    assert credential_call < start_call
    assert (base / "credentials.json").stat().st_mode & 0o777 == 0o600


def test_agent_script_is_valid_python_and_uses_stdin_payload(node):
    source = agent_source(node, "check")
    compile(source, "ssh-agent", "exec")
    assert "main(json.loads(" in source


def test_existing_compose_project_is_not_replaced(node, tmp_path, monkeypatch):
    base = tmp_path / "new-path"
    monkeypatch.setattr(
        remote_agent.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 3, "", "")
    )
    monkeypatch.setattr(remote_agent, "run", lambda args, **kwargs: "existing-container-id")
    with pytest.raises(RuntimeError, match="project already exists"):
        remote_agent.deploy({"node": node.model_dump(), "action": "fresh"}, base)
    assert not base.exists()


def test_credential_timeout_does_not_leak_password(monkeypatch):
    args = ["docker", "setting", "-password", "never-log-this-password"]

    def fail(*a, **kwargs):
        raise subprocess.TimeoutExpired(args, 10)

    monkeypatch.setattr(remote_agent.subprocess, "run", fail)
    with pytest.raises(RuntimeError) as exc:
        remote_agent.run(args, timeout=10)
    assert "never-log-this-password" not in str(exc.value)

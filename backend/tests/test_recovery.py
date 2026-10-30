import base64
import os
import sqlite3
import subprocess
import sys

import pytest

from app.agent.context import AgentContext
from app.agent.database import PanelDatabase
from app.agent.deployment import DeploymentService
from app.agent.diagnostics import Diagnostics
from app.agent.host import HostEnvironment
from app.infrastructure.execution import RemoteAgentBuilder
from app.ports import BackupValidator
from framework.database import SQLiteSnapshots
from framework.entities import ValidationError
from framework.network import CommandRunner, ProcessError
from tests.conftest import create_database


@pytest.fixture
def payload(node, renderer, settings):
    return {
        "node": node.model_dump(mode="json"),
        "action": "fresh",
        "files": renderer.artifacts(node),
        "runtime": {
            "deployment": settings.deployment.model_dump(),
            "limits": settings.limits.model_dump(),
        },
    }


@pytest.fixture
def context(payload):
    return AgentContext(payload)


@pytest.fixture
def panel_database(context):
    return PanelDatabase(context)


@pytest.fixture
def deployment(context):
    host = HostEnvironment(context)
    database = PanelDatabase(context)
    return DeploymentService(context, host, database, Diagnostics(context, host))


def test_snapshot_checks_integrity_and_preserves_clients(db_file, tmp_path, container):
    snapshot = tmp_path / "copy.db"
    SQLiteSnapshots().snapshot(db_file, snapshot)
    container.resolve(BackupValidator).validate(snapshot.read_bytes())
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
        destination = tmp_path / "snapshot.db"
        SQLiteSnapshots().snapshot(source, destination)
        with sqlite3.connect(destination) as db:
            assert (
                db.execute("SELECT settings FROM inbounds").fetchone()[0] == "new-committed-client"
            )


@pytest.mark.parametrize("raw", [b"", b"not sqlite", b"SQLite format 3\x00broken"])
def test_corrupt_backups_are_rejected(raw, container):
    with pytest.raises(ValidationError):
        container.resolve(BackupValidator).validate(raw)


def test_unrelated_sqlite_file_rejected(tmp_path, container):
    path = tmp_path / "other.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE wrong (x)")
    with pytest.raises(ValidationError, match="3x-ui"):
        container.resolve(BackupValidator).validate(path.read_bytes())


def test_listener_patch_preserves_identities_and_routing(node, db_file, panel_database):
    panel_database.configure_listeners(db_file, node.model_dump(), restoring=True)
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


def test_restore_refuses_subscription_path_change_atomically(node, db_file, panel_database):
    data = node.model_dump()
    data["panel"]["subscription_path"] = "/different/"
    with pytest.raises(RuntimeError, match="subscription_path"):
        panel_database.configure_listeners(db_file, data, restoring=True)
    with sqlite3.connect(db_file) as db:
        assert db.execute("SELECT value FROM settings WHERE key='webListen'").fetchone() is None


def test_deploy_refuses_existing_files_before_any_commands(
    payload, deployment, tmp_path, monkeypatch
):
    base = tmp_path / "node"
    base.mkdir()
    original = base / "important.db"
    original.write_bytes(b"do not delete")
    monkeypatch.setattr(
        deployment.context, "command", lambda *args, **kwargs: pytest.fail("No command should run")
    )
    with pytest.raises(RuntimeError, match="not empty"):
        deployment.deploy(payload, base)
    assert original.read_bytes() == b"do not delete"


def mock_environment(deployment, monkeypatch, run):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 3, "", "")
    )
    monkeypatch.setattr(deployment.context, "status", lambda args: 3)
    monkeypatch.setattr(deployment.context, "command", run)
    monkeypatch.setattr(deployment.host, "require_free", lambda port: None)
    monkeypatch.setattr(deployment.host, "port_open", lambda port: True)
    monkeypatch.setattr(deployment.diagnostics, "check", lambda *args: None)


def test_restore_to_new_directory_never_recreates_users(
    payload, deployment, db_file, tmp_path, monkeypatch
):
    base = tmp_path / "restored"
    calls = []
    mock_environment(deployment, monkeypatch, lambda args, **kwargs: calls.append(args) or "")
    payload.update(action="restore", backup=base64.b64encode(db_file.read_bytes()).decode())
    deployment.deploy(payload, base)
    assert not any("setting" in call for call in calls)
    assert ["docker", "compose", "-f", str(base / "compose.yaml"), "up", "-d"] in calls
    with sqlite3.connect(base / "db/x-ui.db") as db:
        assert db.execute("SELECT username FROM users").fetchone()[0] == "original-admin"


def test_fresh_initializes_credentials_before_start(payload, deployment, tmp_path, monkeypatch):
    base = tmp_path / "fresh"
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if "setting" in args:
            create_database(base / "db/x-ui.db")
        return ""

    mock_environment(deployment, monkeypatch, fake_run)
    deployment.deploy(payload, base)
    assert next(i for i, c in enumerate(calls) if "setting" in c) < next(
        i for i, c in enumerate(calls) if "up" in c
    )
    assert (base / "credentials.json").is_file()
    if os.name != "nt":  # The deployment target is Linux; Windows stat cannot model its modes.
        assert (base / "credentials.json").stat().st_mode & 0o777 == 0o600


def test_existing_compose_project_is_not_replaced(payload, deployment, tmp_path, monkeypatch):
    base = tmp_path / "new-path"
    mock_environment(deployment, monkeypatch, lambda *a, **k: "existing-container-id")
    with pytest.raises(RuntimeError, match="project already exists"):
        deployment.deploy(payload, base)
    assert not base.exists()


def test_credential_timeout_does_not_leak_password(monkeypatch):
    args = ["docker", "setting", "-password", "never-log-this-password"]

    def fail(*a, **kwargs):
        raise subprocess.TimeoutExpired(args, 10)

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(ProcessError) as error:
        CommandRunner().run(args, timeout=10, sensitive=True)
    assert "never-log-this-password" not in str(error.value)


def test_remote_bundle_works_without_site_packages(node, container, tmp_path):
    script = container.resolve(RemoteAgentBuilder).build(node, "check")
    compile(script, "remote-agent", "exec")
    script = script.replace("agent.run()", 'agent.context.emit("isolated bundle imported")')
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-"],
        input=script,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "isolated bundle imported" in result.stdout


def test_doctor_checks_configured_tunnel_and_proxy(context, monkeypatch, capsys):
    from contextlib import nullcontext
    from types import SimpleNamespace

    from app.entities import Node

    data = context.node
    data["tunnels"] = [{"name": "gb", "host": "203.0.113.20"}]
    data["probe"] = {"socks_port": 10808, "url": "https://example.com/check"}
    node = Node.model_validate(data).model_dump()
    context.node = node
    host = HostEnvironment(context)
    calls = []
    monkeypatch.setattr(host, "port_open", lambda port: True)
    monkeypatch.setattr(context, "status", lambda args: calls.append(args) or 0)
    monkeypatch.setattr(context, "command", lambda args, **kwargs: calls.append(args) or "")
    monkeypatch.setattr("app.agent.diagnostics.shutil.which", lambda exe: "/usr/bin/" + exe)
    opener = SimpleNamespace(open=lambda *a, **kw: nullcontext(SimpleNamespace(status=200)))
    monkeypatch.setattr("app.agent.diagnostics.urllib.request.build_opener", lambda *a: opener)
    Diagnostics(context, host).check(node, context.directory())
    assert any("omsi-test-node-gb.service" in call for call in calls)
    assert any("socks5h://127.0.0.1:10808" in call for call in calls)
    assert "HTTPS request through configured SOCKS outbound: OK" in capsys.readouterr().out

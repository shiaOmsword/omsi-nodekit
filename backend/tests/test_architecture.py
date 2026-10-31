import ast
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import Field

from app.config import DeploymentSettings, Limits, ServerSettings, Settings
from app.container import build_container
from app.create_app import create_app
from app.entities import Job, JobAction, JobStatus, NodeFactory
from app.infrastructure.bootstrap import StorageBootstrap
from app.infrastructure.schema import MIGRATIONS
from app.ports import ArtifactRenderer, NodeRepository
from app.services import NodeService
from framework.database import Migration, SQLiteDatabase
from framework.entities import (
    ConflictError,
    Entity,
    EntityFactory,
    JsonCodec,
    ValidationError,
    YamlCodec,
)
from framework.network import CommandRunner, ProcessError
from framework.tasks import TaskScheduler


def test_framework_has_no_application_dependencies():
    root = Path(__file__).parents[1] / "src/framework"
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else []
            )
            assert not any(name == "app" or name.startswith("app.") for name in names), path


def test_entities_and_services_do_not_import_http_or_io_implementations():
    root = Path(__file__).parents[1] / "src/app"
    for directory in ("entities", "services"):
        for path in (root / directory).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                names = (
                    [node.module or ""]
                    if isinstance(node, ast.ImportFrom)
                    else [a.name for a in node.names]
                    if isinstance(node, ast.Import)
                    else []
                )
                assert not any(
                    name.split(".")[0] in {"fastapi", "starlette", "sqlite3", "subprocess"}
                    or name.startswith("app.infrastructure")
                    for name in names
                ), path


def test_generic_factory_builds_models_and_redacts_invalid_input():
    class Person(Entity):
        age: int = Field(ge=0)

    factory = EntityFactory(YamlCodec(), JsonCodec())
    assert factory.from_json(Person, '{"age":4}').age == 4
    assert factory.from_yaml(Person, "age: 8").age == 8
    with pytest.raises(ValidationError) as error:
        factory.from_yaml(Person, "age: secret-password")
    assert error.value.details == [{"field": "age", "code": "int_parsing"}]
    assert "secret-password" not in str(error.value)


def test_final_job_cannot_change_state():
    job = (
        Job.create("node", JobAction.CHECK)
        .transition(JobStatus.RUNNING)
        .transition(JobStatus.SUCCEEDED)
    )
    with pytest.raises(ConflictError):
        job.transition(JobStatus.RUNNING)


def test_container_override_replaces_adapter_without_globals(settings, node_yaml):
    class FakeRenderer(ArtifactRenderer):
        def artifacts(self, node):
            return {"fake.conf": node.id}

        def plan(self, node, action):
            return {"action": action, "files": self.artifacts(node)}

    fake = FakeRenderer()
    container = build_container(settings, overrides={ArtifactRenderer: fake})
    try:
        assert container.resolve(NodeService).renderer is fake
        assert container.resolve(NodeService).validate(node_yaml)["files"] == {
            "fake.conf": "test-node"
        }
    finally:
        container.resolve(TaskScheduler).close()


def test_policies_drive_rendering_and_limits(tmp_path, node_yaml, node):
    settings = Settings(
        data_dir=tmp_path / "custom",
        deployment=DeploymentSettings(remote_root="/srv/nodes", service_prefix="custom"),
        limits=Limits(config_bytes=1024),
    )
    container = build_container(settings)
    try:
        renderer = container.resolve(ArtifactRenderer)
        assert renderer.plan(node, JobAction.FRESH)["remote_dir"] == "/srv/nodes/test-node"
        assert "name: custom-test-node" in renderer.artifacts(node)["compose.yaml"]
        with pytest.raises(ValidationError, match="exceeds"):
            container.resolve(NodeFactory).from_yaml(node_yaml + "#" * 1100)
    finally:
        container.resolve(TaskScheduler).close()


def test_server_origin_uses_configured_port(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "custom",
        frontend_dir=tmp_path / "absent",
        server=ServerSettings(port=8877),
    )
    with TestClient(
        create_app(settings),
        base_url="http://127.0.0.1:8877",
        headers={"X-Nodekit-Request": "1", "Origin": "http://127.0.0.1:8877"},
    ) as client:
        assert client.get("/api/health").status_code == 200
        assert (
            client.get("/api/health", headers={"Origin": "http://127.0.0.1:8765"}).status_code
            == 403
        )


def test_migration_preserves_existing_unversioned_database(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE nodes(id TEXT PRIMARY KEY,name TEXT,yaml TEXT,revision TEXT)")
        db.execute("INSERT INTO nodes VALUES ('legacy','Legacy','id: legacy','abc')")
    settings = Settings(data_dir=tmp_path, database_name="legacy.db")
    container = build_container(settings)
    try:
        container.resolve(StorageBootstrap).initialize()
        assert container.resolve(NodeRepository).get("legacy").name == "Legacy"
        with sqlite3.connect(path) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == max(
                m.version for m in MIGRATIONS
            )
    finally:
        container.resolve(TaskScheduler).close()


def test_failed_migration_rolls_back(tmp_path):
    database = SQLiteDatabase(tmp_path / "test.db")
    with pytest.raises(sqlite3.DatabaseError):
        database.initialize([Migration(1, "CREATE TABLE should_rollback(id); NOT VALID SQL;")])
    with database.connect() as db:
        assert (
            db.execute("SELECT 1 FROM sqlite_master WHERE name='should_rollback'").fetchone()
            is None
        )
        assert db.execute("PRAGMA user_version").fetchone()[0] == 0


def test_process_stream_timeout_is_bounded():
    code = "import time; print('started',flush=True); time.sleep(10)"
    stream = CommandRunner().stream([sys.executable, "-c", code], "", timeout=0.2)
    assert next(stream).strip() == "started"
    with pytest.raises(ProcessError, match="timed out"):
        list(stream)


def test_nested_environment_settings_are_applied(monkeypatch, tmp_path):
    monkeypatch.setenv("NODEKIT_SSH__OPERATION_TIMEOUT", "321")
    monkeypatch.setenv("NODEKIT_DEPLOYMENT__REMOTE_ROOT", "/srv/custom")
    configured = Settings(data_dir=tmp_path / "runtime", _env_file=None)
    assert configured.ssh.operation_timeout == 321
    assert configured.deployment.remote_root == "/srv/custom"

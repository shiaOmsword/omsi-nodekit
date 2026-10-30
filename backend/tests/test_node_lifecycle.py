"""Regression coverage for local node lifecycle; nothing is sent to the VPS."""

import pytest
from fastapi.testclient import TestClient

from app.create_app import create_app
from app.entities import Job, JobAction
from app.infrastructure.schema import MIGRATIONS
from app.ports import JobRepository, NodeRepository
from framework.database import SQLiteDatabase


@pytest.fixture
def client(settings, container):
    with TestClient(
        create_app(settings, container=container),
        base_url="http://127.0.0.1:8765",
        headers={"X-Nodekit-Request": "1"},
    ) as instance:
        yield instance


def test_node_states_persist_through_yaml_updates_and_block_archived_jobs(client, node_yaml):
    stored = client.put("/api/nodes/test-node", json={"yaml": node_yaml})
    assert stored.status_code == 200
    assert stored.json()["data"]["state"] == "active"

    hidden = client.patch("/api/nodes/test-node/state", json={"state": "hidden"})
    assert hidden.status_code == 200
    assert hidden.json()["data"]["state"] == "hidden"
    assert client.get("/api/nodes").json()["data"][0]["state"] == "hidden"

    edited = client.put(
        "/api/nodes/test-node", json={"yaml": node_yaml.replace("Test node", "Renamed node")}
    )
    assert edited.status_code == 200
    assert edited.json()["data"]["state"] == "hidden"

    archived = client.patch("/api/nodes/test-node/state", json={"state": "archived"})
    assert archived.status_code == 200
    assert archived.json()["data"]["state"] == "archived"
    rejected = client.post(
        "/api/nodes/test-node/jobs",
        json={"action": "check", "revision": archived.json()["data"]["revision"]},
    )
    assert rejected.status_code == 409
    assert client.get("/api/jobs").json()["data"] == []

    active = client.patch("/api/nodes/test-node/state", json={"state": "active"})
    assert active.status_code == 200
    assert active.json()["data"]["state"] == "active"


def test_delete_is_local_and_preserves_completed_job_history(client, container, node_yaml):
    client.put("/api/nodes/test-node", json={"yaml": node_yaml})
    jobs = container.resolve(JobRepository)
    nodes = container.resolve(NodeRepository)
    job = Job.create("test-node", JobAction.CHECK)
    jobs.enqueue(job, nodes.get("test-node").revision)
    jobs.recover()

    result = client.delete("/api/nodes/test-node")
    assert result.status_code == 200
    assert result.json()["data"] == {"deleted": True, "remote_untouched": True}
    assert client.get("/api/nodes/test-node").status_code == 404
    assert client.get("/api/jobs").json()["data"][0]["id"] == job.id
    assert client.delete("/api/nodes/test-node").status_code == 404


def test_running_operation_guards_hide_archive_and_delete(client, container, node_yaml):
    client.put("/api/nodes/test-node", json={"yaml": node_yaml})
    job = Job.create("test-node", JobAction.BACKUP)
    container.resolve(JobRepository).enqueue(
        job, container.resolve(NodeRepository).get("test-node").revision
    )
    assert client.patch("/api/nodes/test-node/state", json={"state": "hidden"}).status_code == 409
    assert client.patch("/api/nodes/test-node/state", json={"state": "archived"}).status_code == 409
    assert client.delete("/api/nodes/test-node").status_code == 409


@pytest.mark.parametrize("payload", [{"state": "unknown"}, {"state": "ARCHIVED"}, {}])
def test_unknown_lifecycle_state_is_rejected(client, node_yaml, payload):
    client.put("/api/nodes/test-node", json={"yaml": node_yaml})
    assert client.patch("/api/nodes/test-node/state", json=payload).status_code == 422


def test_migration_from_v2_preserves_saved_yaml(tmp_path):
    database = SQLiteDatabase(tmp_path / "old.db")
    database.initialize(MIGRATIONS[:2])
    with database.connect() as db:
        db.execute(
            "INSERT INTO nodes (id,name,yaml,revision) VALUES (?,?,?,?)",
            ("test-node", "Original", "id: test-node", "revision"),
        )
    database.initialize(MIGRATIONS)
    with database.connect() as db:
        row = db.execute("SELECT yaml, state FROM nodes WHERE id='test-node'").fetchone()
        assert row["yaml"] == "id: test-node"
        assert row["state"] == "active"

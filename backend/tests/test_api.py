import pytest
from fastapi.testclient import TestClient

from app.app import create_app
from app.config import Settings
from app.storage import Store

HEADERS = {"X-Nodekit-Request": "1"}


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "data", frontend_dir=tmp_path / "absent"))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers=HEADERS) as client:
        yield client


def test_save_preview_and_stale_revision(client, node_yaml):
    saved = client.put("/api/nodes/test-node", json={"yaml": node_yaml})
    assert saved.status_code == 200
    plan = client.get("/api/nodes/test-node/plan?action=fresh").json()
    assert plan["revision"] == saved.json()["revision"]
    assert "compose.yaml" in plan["files"]
    changed = node_yaml.replace("Test node", "Renamed node")
    assert client.put("/api/nodes/test-node", json={"yaml": changed}).status_code == 200
    rejected = client.post(
        "/api/nodes/test-node/jobs", json={"action": "fresh", "revision": plan["revision"]}
    )
    assert rejected.status_code == 409


def test_restore_has_no_silent_fresh_fallback(client, node_yaml):
    saved = client.put("/api/nodes/test-node", json={"yaml": node_yaml}).json()
    result = client.post(
        "/api/nodes/test-node/jobs", json={"action": "restore", "revision": saved["revision"]}
    )
    assert result.status_code == 422
    assert client.get("/api/jobs").json() == []


def test_backup_upload_validation_and_download(client, db_file):
    invalid = client.post("/api/backups?filename=test.db", content=b"broken")
    assert invalid.status_code == 422
    result = client.post("/api/backups?filename=x-ui.db", content=db_file.read_bytes())
    assert result.status_code == 201
    backup = result.json()
    assert len(backup["sha256"]) == 64
    assert client.get(f"/api/backups/{backup['id']}/download").content == db_file.read_bytes()


def test_browser_security_blocks_foreign_origin_and_missing_header(client, node_yaml):
    assert (
        client.post(
            "/api/config/validate",
            json={"yaml": node_yaml},
            headers={"Origin": "https://evil.example"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/config/validate", json={"yaml": node_yaml}, headers={"X-Nodekit-Request": ""}
        ).status_code
        == 403
    )
    assert client.get("/api/nodes", headers={"Host": "evil.example"}).status_code == 403


def test_unknown_yaml_keys_fail_instead_of_being_ignored(client, node_yaml):
    result = client.post("/api/config/validate", json={"yaml": node_yaml + "typo: true\n"})
    assert result.status_code == 422


def test_job_runs_in_background_and_failure_is_visible(client, node_yaml, monkeypatch):
    def fake_execute(store, job_id, node, action, backup):
        store.start(job_id)
        store.event(job_id, "SSH host-key verification failed", "error")
        store.finish(job_id, "failed", "SSH failed")

    monkeypatch.setattr("app.app.execute", fake_execute)
    saved = client.put("/api/nodes/test-node", json={"yaml": node_yaml}).json()
    result = client.post(
        "/api/nodes/test-node/jobs", json={"action": "check", "revision": saved["revision"]}
    )
    assert result.status_code == 202
    client.app.state.pool.shutdown(wait=True)
    job = client.get(f"/api/jobs/{result.json()['id']}").json()
    assert job["status"] == "failed"
    assert job["events"][0]["level"] == "error"


def test_job_lock_and_restart_recovery(tmp_path, node, node_yaml):
    store = Store(tmp_path / "data")
    revision = store.save_node(node, node_yaml)["revision"]
    job_id = store.create_job(node.id, "backup", revision)
    with pytest.raises(ValueError, match="Another operation"):
        store.create_job(node.id, "fresh", revision)
    store.recover_jobs()
    assert store.job(job_id)["status"] == "interrupted"
    assert "check remote services" in store.job(job_id)["error"]

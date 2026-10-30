import pytest
from fastapi.testclient import TestClient

from app.create_app import create_app
from app.entities import ExecutionEvent, Job, JobAction, JobStatus, StoredNode
from app.ports import JobRepository, NodeExecutor, NodeRepository
from framework.entities import ConflictError

HEADERS = {"X-Nodekit-Request": "1"}


@pytest.fixture
def client(settings, container):
    application = create_app(settings, container=container)
    with TestClient(
        application, base_url=f"http://127.0.0.1:{settings.server.port}", headers=HEADERS
    ) as client:
        yield client


def data(response):
    body = response.json()
    assert set(body) == {"ok", "data", "error", "meta"}
    assert body["ok"] is True and body["error"] is None
    assert body["meta"]["request_id"] == response.headers["x-request-id"]
    return body["data"]


def test_save_preview_and_stale_revision(client, node_yaml):
    saved = client.put("/api/nodes/test-node", json={"yaml": node_yaml})
    assert saved.status_code == 200
    preview = data(client.get("/api/nodes/test-node/plan?action=fresh"))
    assert preview["revision"] == data(saved)["revision"]
    assert "compose.yaml" in preview["files"]
    assert (
        client.put(
            "/api/nodes/test-node", json={"yaml": node_yaml.replace("Test node", "Renamed node")}
        ).status_code
        == 200
    )
    rejected = client.post(
        "/api/nodes/test-node/jobs", json={"action": "fresh", "revision": preview["revision"]}
    )
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "conflict"


def test_restore_has_no_silent_fresh_fallback(client, node_yaml):
    saved = data(client.put("/api/nodes/test-node", json={"yaml": node_yaml}))
    result = client.post(
        "/api/nodes/test-node/jobs", json={"action": "restore", "revision": saved["revision"]}
    )
    assert result.status_code == 422
    assert result.json()["error"]["code"] == "validation_error"
    assert data(client.get("/api/jobs")) == []


def test_backup_upload_validation_and_download(client, db_file):
    invalid = client.post("/api/backups?filename=test.db", content=b"broken")
    assert invalid.status_code == 422
    backup = data(client.post("/api/backups?filename=x-ui.db", content=db_file.read_bytes()))
    assert len(backup["sha256"]) == 64
    downloaded = client.get(f"/api/backups/{backup['id']}/download")
    assert downloaded.content == db_file.read_bytes()
    assert downloaded.headers["content-type"] == "application/octet-stream"


@pytest.mark.parametrize(
    "headers",
    [{"Origin": "https://evil.example"}, {"X-Nodekit-Request": ""}, {"Host": "evil.example"}],
)
def test_browser_security_is_an_enveloped_error(client, node_yaml, headers):
    response = client.post("/api/config/validate", json={"yaml": node_yaml}, headers=headers)
    assert response.status_code == 403
    body = response.json()
    assert body["ok"] is False and body["data"] is None
    assert body["error"]["code"] == "forbidden"
    assert body["meta"]["request_id"] == response.headers["x-request-id"]


def test_unknown_yaml_keys_fail_instead_of_being_ignored(client, node_yaml):
    result = client.post("/api/config/validate", json={"yaml": node_yaml + "typo: secret-value\n"})
    assert result.status_code == 422
    assert "secret-value" not in result.text
    assert result.json()["error"]["details"][0]["field"] == "typo"


def test_dependency_replacement_runs_background_job_without_ssh(settings, node_yaml):
    from app.container import build_container
    from framework.tasks import TaskScheduler

    class FakeExecutor(NodeExecutor):
        def execute(self, node, action, backup):
            yield ExecutionEvent(message="Injected executor ran")

    container = build_container(settings, overrides={NodeExecutor: FakeExecutor()})
    with TestClient(
        create_app(settings, container=container), base_url="http://127.0.0.1:8765", headers=HEADERS
    ) as client:
        saved = data(client.put("/api/nodes/test-node", json={"yaml": node_yaml}))
        result = client.post(
            "/api/nodes/test-node/jobs", json={"action": "check", "revision": saved["revision"]}
        )
        assert result.status_code == 202
        job_id = data(result)["id"]
        container.resolve(TaskScheduler).close()
        job = data(client.get(f"/api/jobs/{job_id}"))
        assert job["status"] == "succeeded"
        assert job["events"][0]["message"] == "Injected executor ran"


def test_job_lock_and_restart_recovery(container, node, node_yaml):
    nodes = container.resolve(NodeRepository)
    jobs = container.resolve(JobRepository)
    revision = nodes.save(StoredNode.create(node, node_yaml)).revision
    job = Job.create(node.id, JobAction.BACKUP)
    jobs.enqueue(job, revision)
    with pytest.raises(ConflictError, match="Another operation"):
        jobs.enqueue(Job.create(node.id, JobAction.FRESH), revision)
    jobs.recover()
    assert jobs.get(job.id).status == JobStatus.INTERRUPTED
    assert "check remote services" in jobs.get(job.id).error


@pytest.mark.parametrize(
    "path",
    [
        "/api/no-such-route",
        "/api/nodes/missing",
        "/api/jobs/missing",
        "/api/backups/missing/download",
    ],
)
def test_not_found_uses_same_contract(client, path):
    response = client.get(path)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_request_schema_errors_do_not_echo_input(client):
    response = client.post(
        "/api/nodes/test/jobs", json={"action": "SECRET", "revision": "not-a-hash"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "SECRET" not in response.text


def test_unexpected_failure_does_not_leak_details(client, container, monkeypatch):
    from app.services import NodeService

    def fail():
        raise RuntimeError("super-secret-password")

    monkeypatch.setattr(container.resolve(NodeService), "list", fail)
    response = client.get("/api/nodes")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "super-secret-password" not in response.text


def test_node_id_mismatch_is_a_catalogue_validation_error(client, node_yaml):
    from framework.messages import MessageKey, text

    response = client.put("/api/nodes/different", json={"yaml": node_yaml})
    assert response.status_code == 422
    assert response.json()["error"]["message"] == text(MessageKey.NODE_ID_MISMATCH)

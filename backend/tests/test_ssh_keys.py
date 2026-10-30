import os
import shutil

import pytest
import yaml
from fastapi.testclient import TestClient

from app.create_app import create_app
from app.entities import SSHKeyRequest
from app.ports import SSHKeyFiles, SSHKeyRepository
from app.services import SSHKeyService
from framework.entities import InfrastructureError
from framework.network import CommandRunner, ProcessError
from framework.network.keys import KeyOptions, OpenSSHKeys


@pytest.mark.skipif(
    not shutil.which("ssh-keygen"), reason="OpenSSH ssh-keygen must be installed locally"
)
def test_real_key_generation_binding_and_delete_guard(settings, container, node_yaml):
    with TestClient(
        create_app(settings, container=container),
        base_url="http://127.0.0.1:8765",
        headers={"X-Nodekit-Request": "1"},
    ) as client:
        response = client.post("/api/ssh-keys", json={"name": "Москва · тест"})
        assert response.status_code == 201, response.text
        key = response.json()["data"]
        assert key["public_key"].startswith("ssh-ed25519 ")
        assert key["fingerprint"].startswith("SHA256:")
        assert "PRIVATE" not in response.text and "identity_file" not in key
        assert client.get("/api/ssh-keys").json()["data"] == [key]
        identity = container.resolve(SSHKeyFiles).identity(key["id"])
        assert identity.is_file()
        if os.name != "nt":
            assert identity.stat().st_mode & 0o777 == 0o600
            assert identity.parent.stat().st_mode & 0o777 == 0o700
        selected = client.post("/api/config/ssh-key", json={"yaml": node_yaml, "key_id": key["id"]})
        assert selected.status_code == 200
        updated = selected.json()["data"]["yaml"]
        assert yaml.safe_load(updated)["ssh"]["key_id"] == key["id"]
        assert client.put("/api/nodes/test-node", json={"yaml": updated}).status_code == 200
        assert client.delete(f"/api/ssh-keys/{key['id']}").status_code == 409
        cleared = client.post("/api/config/ssh-key", json={"yaml": updated, "key_id": None}).json()[
            "data"
        ]["yaml"]
        assert "key_id" not in yaml.safe_load(cleared)["ssh"]
        client.put("/api/nodes/test-node", json={"yaml": cleared})
        assert client.delete(f"/api/ssh-keys/{key['id']}").status_code == 200
        assert not identity.exists()
        assert client.get("/api/ssh-keys").json()["data"] == []


def test_generation_failure_leaves_no_metadata_or_files(container, monkeypatch, settings):
    files = container.resolve(SSHKeyFiles)

    def fail(_):
        raise InfrastructureError("ssh-keygen is unavailable")

    monkeypatch.setattr(files, "generate", fail)
    with pytest.raises(InfrastructureError):
        container.resolve(SSHKeyService).create(SSHKeyRequest(name="test"))
    assert container.resolve(SSHKeyRepository).list() == []


def test_missing_key_and_path_traversal_are_rejected(settings):
    keys = OpenSSHKeys(CommandRunner(), KeyOptions(settings.data_dir / "ssh-keys"))
    with pytest.raises(ProcessError, match="ID"):
        keys.identity("../../outside")
    with pytest.raises(ProcessError, match="missing"):
        keys.identity("a" * 32)


def test_custom_installation_and_key_selection_use_the_api(settings, container, node_yaml):
    with TestClient(
        create_app(settings, container=container),
        base_url="http://127.0.0.1:8765",
        headers={"X-Nodekit-Request": "1"},
    ) as client:
        changed = client.post(
            "/api/config/installation", json={"yaml": node_yaml, "installation": "native"}
        )
        assert changed.status_code == 200
        updated = changed.json()["data"]["yaml"]
        assert yaml.safe_load(updated)["panel"]["installation"] == "native"
        saved = client.put("/api/nodes/test-node", json={"yaml": updated}).json()["data"]
        assert client.get("/api/nodes/test-node/plan?action=fresh").status_code == 422
        assert (
            client.post(
                "/api/nodes/test-node/jobs", json={"action": "fresh", "revision": saved["revision"]}
            ).status_code
            == 422
        )
        selected = client.post("/api/config/ssh-key", json={"yaml": updated, "key_id": "a" * 32})
        assert selected.status_code == 404
        invalid = client.post(
            "/api/config/ssh-key", json={"yaml": updated, "key_id": "../../private"}
        )
        assert invalid.status_code == 422
        assert "../../private" not in invalid.text


def test_metadata_rollback_removes_generated_pair(container, monkeypatch):
    removed = []
    files = container.resolve(SSHKeyFiles)
    monkeypatch.setattr(files, "generate", lambda _: ("ssh-ed25519 fixture", "SHA256:fixture"))
    monkeypatch.setattr(files, "remove", removed.append)

    def fail(_):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(container.resolve(SSHKeyRepository), "save", fail)
    with pytest.raises(RuntimeError):
        container.resolve(SSHKeyService).create(SSHKeyRequest(name="test"))
    assert len(removed) == 1


def test_windows_key_acl_is_applied_to_current_sid_without_localized_names(tmp_path, monkeypatch):
    import framework.network.keys as module

    calls = []

    class Runner:
        def run(self, args, **kwargs):
            calls.append(args)
            return '"DESKTOP\\user","S-1-5-21-1234"' if args[0] == "whoami" else ""

    keys = OpenSSHKeys(Runner(), KeyOptions(tmp_path))
    # _restrict does not instantiate a platform-dependent Path after this patch.
    monkeypatch.setattr(module.os, "name", "nt")
    keys._restrict(tmp_path, directory=True)
    assert calls[-1] == [
        "icacls",
        str(tmp_path),
        "/inheritance:r",
        "/grant:r",
        "*S-1-5-21-1234:(OI)(CI)F",
    ]

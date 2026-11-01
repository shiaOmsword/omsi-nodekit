import base64
import io
import json
import os
import socket
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from app.agent.adaptive_deployment import AdaptiveDeployment
from app.agent.caddy_reuse import ExistingCaddy
from app.agent.context import AgentContext
from app.agent.database import PanelDatabase
from app.agent.diagnostics import Diagnostics
from app.agent.host import HostEnvironment
from app.agent.native_release import NativeRelease
from app.agent.panel_api import InboundProvisioner, PanelAPI
from app.create_app import create_app
from app.entities import (
    DeploymentTarget,
    DiscoverySelection,
    InstallationReport,
    Job,
    JobAction,
    Node,
)
from app.ports import JobRepository, NodeRepository
from app.services import NodeService
from app.services.discovery_config import DiscoveryConfigService
from framework.entities import ValidationError
from tests.conftest import create_database

ORIGINAL_NATIVE_INSTALL = NativeRelease.install


def report(**changes):
    return InstallationReport(
        observed_at="2026-10-30T15:00:00Z", ssh_host="203.0.113.10", ssh_port=22, **changes
    )


def saved_report(container, node_yaml, inventory):
    stored = container.resolve(NodeService).save("test-node", node_yaml)
    job = Job.create(stored.id, JobAction.CHECK)
    jobs = container.resolve(JobRepository)
    jobs.enqueue(job, stored.revision)
    jobs.save_report(job.id, inventory)
    return job


def test_caddy_without_panel_suggests_native_exit_and_preserves_credentials(container, node_yaml):
    inventory = report(
        caddy=[
            {
                "id": "docker:abc",
                "installation": "docker",
                "active": True,
                "container": "shared-caddy",
                "network_mode": "bridge",
                "host_gateway": "172.18.0.1",
                "published_ports": ["0.0.0.0:443->443/tcp"],
                "config_path": "/etc/caddy/Caddyfile",
            }
        ]
    )
    job = saved_report(container, node_yaml, inventory)
    text = node_yaml.replace("sudo: false", "sudo: true").replace(
        "sudo_password: null", "sudo_password: 'fixture-secret'"
    )
    result = container.resolve(DiscoveryConfigService).suggest(
        DiscoverySelection(yaml=text, job_id=job.id, caddy_id="docker:abc")
    )
    node = container.resolve(NodeService).factory.from_yaml(result["yaml"])
    assert node.deployment.panel_runtime == "native"
    assert node.deployment.caddy_mode == "existing"
    assert node.deployment.subscription_bind == "172.18.0.1"
    assert node.caddy.https_port == 443
    assert node.ssh.sudo_password.get_secret_value() == "fixture-secret"
    assert container.resolve(NodeRepository).get("test-node").yaml == node_yaml


def test_existing_panel_suggestions_copy_observed_values_only(container, node_yaml):
    inventory = report(
        panels=[
            {
                "id": "native:x-ui",
                "installation": "native",
                "active": True,
                "service": "x-ui",
                "database_path": "/etc/x-ui/x-ui.db",
                "settings": {
                    "webPort": "40768",
                    "subPort": "2096",
                    "webBasePath": "/",
                    "subPath": "/default/",
                },
                "defaulted_settings": ["subPath"],
            }
        ]
    )
    job = saved_report(container, node_yaml, inventory)
    result = container.resolve(DiscoveryConfigService).suggest(
        DiscoverySelection(yaml=node_yaml, job_id=job.id, panel_id="native:x-ui")
    )
    node = container.resolve(NodeService).factory.from_yaml(result["yaml"])
    assert node.panel.port == 40768 and node.panel.subscription_port == 2096
    assert node.panel.base_path == "/" and node.panel.subscription_path == "/sub/"
    assert node.panel.installation == "native" and node.deployment is None


def test_suggestions_reject_another_endpoint_and_ambiguous_selection(container, node_yaml):
    inventory = report(panels=[{"id": "native:x-ui", "installation": "native", "active": True}])
    job = saved_report(container, node_yaml, inventory)
    service = container.resolve(DiscoveryConfigService)
    with pytest.raises(ValidationError, match="Choose an installation"):
        service.suggest(DiscoverySelection(yaml=node_yaml, job_id=job.id))
    with pytest.raises(ValidationError, match="SSH endpoint"):
        service.suggest(
            DiscoverySelection(
                yaml=node_yaml.replace("203.0.113.10", "203.0.113.11"), job_id=job.id
            )
        )


def test_deployment_selector_endpoint_returns_a_draft_without_saving(settings, node_yaml):
    with TestClient(
        create_app(settings), base_url="http://127.0.0.1:8765", headers={"X-Nodekit-Request": "1"}
    ) as client:
        response = client.post(
            "/api/config/deployment",
            json={"yaml": node_yaml, "target": {"role": "exit", "panel_runtime": "native"}},
        )
        assert response.status_code == 200, response.text
        assert "panel_runtime: native" in response.json()["data"]["yaml"]
        assert client.get("/api/nodes").json()["data"] == []


@pytest.mark.parametrize(
    "target",
    [
        {"caddy_mode": "existing"},
        {"subscription_bind": "0.0.0.0"},
        {"subscription_bind": "8.8.8.8"},
        {
            "inbounds": [
                {"name": "one", "port": 443, "server_name": "example.com"},
                {"name": "two", "port": 443, "server_name": "example.com"},
            ]
        },
    ],
)
def test_unsafe_or_conflicting_targets_are_rejected(target):
    with pytest.raises(PydanticValidationError):
        DeploymentTarget.model_validate(target)


def test_native_and_docker_rendering_and_port_conflicts(renderer, node):
    native = Node.model_validate(
        {**node.export_config(), "deployment": {"panel_runtime": "native"}}
    )
    files = renderer.artifacts(native)
    assert "compose.yaml" not in files
    assert "XUI_DB_FOLDER=" in files["omsi-test-node-panel.service"]
    assert "SHA256" in " ".join(renderer.plan(native, "fresh")["steps"])
    with pytest.raises(PydanticValidationError):
        Node.model_validate(
            {
                **node.export_config(),
                "deployment": {
                    "inbounds": [
                        {"name": "bad", "port": node.panel.port, "server_name": "example.com"}
                    ]
                },
            }
        )
    docker = Node.model_validate(
        {**node.export_config(), "deployment": {"panel_runtime": "docker"}}
    )
    assert "network_mode: host" in renderer.artifacts(docker)["compose.yaml"]


@pytest.fixture
def adaptive(tmp_path, node, renderer, settings, monkeypatch):
    data = {**node.export_config(), "deployment": {"panel_runtime": "native"}}
    node = Node.model_validate(data)
    unit_dir = tmp_path / "units"
    unit_dir.mkdir()
    policy = {**settings.deployment.model_dump(), "unit_directory": str(unit_dir)}
    payload = {
        "node": node.export_config(),
        "action": "fresh",
        "files": renderer.artifacts(node),
        "runtime": {"deployment": policy, "limits": settings.limits.model_dump()},
    }
    context = AgentContext(payload)
    host = HostEnvironment(context)
    diagnostics = Diagnostics(context, host)
    inspector = SimpleNamespace(
        report={"panels": [], "warnings": [], "capabilities": {"systemctl": True}, "caddy": []}
    )
    deployment = AdaptiveDeployment(context, host, PanelDatabase(context), diagnostics, inspector)
    monkeypatch.setattr(host, "require_endpoint", lambda *a: None)
    monkeypatch.setattr(host, "port_open", lambda *a: True)
    monkeypatch.setattr(diagnostics, "check", lambda *a: None)
    monkeypatch.setattr("app.agent.adaptive_deployment.architecture", lambda: "amd64")
    monkeypatch.setattr(NativeRelease, "install", lambda *a: None)
    return deployment, tmp_path / "new-node", []


def test_native_fresh_needs_no_docker_and_does_not_replace_xui(adaptive, monkeypatch):
    deployment, base, calls = adaptive

    def run(args, **kwargs):
        calls.append(args)
        if "setting" in args:
            create_database(base / "db/x-ui.db")
        return ""

    monkeypatch.setattr(deployment.context, "command", run)
    deployment.deploy(base)
    assert (base / "manifest.json").is_file()
    assert not any("docker" in c for c in calls)
    assert not any("x-ui" in c and "systemctl" in c for c in calls)
    assert ["systemctl", "enable", "--now", "omsi-test-node-panel.service"] in calls


@pytest.mark.parametrize("problem", ["panel", "inventory", "occupied", "unit"])
def test_failed_preflight_has_no_remote_mutations(adaptive, monkeypatch, problem):
    deployment, base, calls = adaptive
    if problem == "panel":
        deployment.inspector.report["panels"] = [{"id": "native:x-ui"}]
    elif problem == "inventory":
        deployment.inspector.report["warnings"] = ["Docker inventory failed"]
    elif problem == "occupied":

        def occupied(*args):
            raise RuntimeError("Port occupied")

        monkeypatch.setattr(deployment.host, "require_endpoint", occupied)
    else:
        path = Path(deployment.context.policy["unit_directory"]) / "omsi-test-node-panel.service"
        path.write_text("owned elsewhere")
    monkeypatch.setattr(deployment.context, "command", lambda *a, **k: pytest.fail("No mutation"))
    with pytest.raises(RuntimeError):
        deployment.deploy(base)
    assert not base.exists()


def test_native_failure_stops_only_owned_unit_and_keeps_database(adaptive, monkeypatch):
    deployment, base, calls = adaptive

    def run(args, **kwargs):
        calls.append(args)
        if "setting" in args:
            create_database(base / "db/x-ui.db")
        return ""

    monkeypatch.setattr(deployment.context, "command", run)

    def failure(*args):
        raise RuntimeError("Readiness failed")

    monkeypatch.setattr(deployment.diagnostics, "check", failure)
    with pytest.raises(RuntimeError, match="Readiness"):
        deployment.deploy(base)
    assert ["systemctl", "disable", "--now", "omsi-test-node-panel.service"] in calls
    assert (base / "db/x-ui.db").is_file()
    assert not (base / "manifest.json").exists()


@pytest.mark.parametrize(
    "name,kind",
    [
        ("../escape", tarfile.REGTYPE),
        ("x-ui/../../escape", tarfile.REGTYPE),
        ("x-ui/link", tarfile.SYMTYPE),
    ],
)
def test_release_archive_rejects_traversal_and_links_before_extracting(tmp_path, name, kind):
    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        valid = tarfile.TarInfo("x-ui/x-ui")
        valid.size = 1
        bundle.addfile(valid, io.BytesIO(b"x"))
        invalid = tarfile.TarInfo(name)
        invalid.type = kind
        invalid.linkname = "/etc/passwd"
        bundle.addfile(invalid)
    destination = tmp_path / "runtime"
    with pytest.raises(RuntimeError, match="unsafe release"):
        NativeRelease.unpack(archive, destination)
    assert not destination.exists()


@pytest.fixture
def shared_caddy(adaptive, tmp_path, monkeypatch):
    deployment, base, _ = adaptive
    path = tmp_path / "SharedCaddyfile"
    original = b"# existing service\nold.example.com {\n respond original\n}\n"
    path.write_bytes(original)
    deployment.context.node["caddy"].update(enabled=True, domain="new.example.com")
    deployment.context.node["deployment"].update(caddy_mode="existing", caddy_id="native:caddy")
    deployment.inspector.report["caddy"] = [
        {
            "id": "native:caddy",
            "installation": "native",
            "active": True,
            "config_source": "file",
            "config_path": str(path),
            "routes": [{"hosts": ["old.example.com"]}],
        }
    ]
    caddy = ExistingCaddy(deployment.context, deployment.inspector)
    calls = []
    monkeypatch.setattr(caddy, "_live", lambda: {})
    monkeypatch.setattr(caddy, "_command", lambda args: calls.append(args) or "{}")
    return caddy, base, path, original, calls


def test_shared_caddy_preserves_routes_and_original_file(shared_caddy):
    caddy, base, path, original, calls = shared_caddy
    caddy.preflight()
    base.mkdir()
    caddy.apply(base, "new.example.com { respond added }\n")
    assert path.read_bytes().startswith(original)
    assert (base / "Caddyfile.original").read_bytes() == original
    caddy.rollback()
    assert path.read_bytes() == original
    assert not any("stop" in c or "restart" in c for c in calls)


def test_shared_caddy_reload_failure_can_restore_exact_original(shared_caddy, monkeypatch):
    caddy, base, path, original, calls = shared_caddy
    caddy.preflight()
    base.mkdir()

    def command(args):
        if "reload" in args and b"added" in path.read_bytes():
            raise RuntimeError("Reload failed")
        return "{}"

    monkeypatch.setattr(caddy, "_command", command)
    with pytest.raises(RuntimeError, match="Reload"):
        caddy.apply(base, "new.example.com { respond added }\n")
    caddy.rollback()
    assert path.read_bytes() == original


def test_shared_caddy_drift_is_rejected_before_writing(shared_caddy):
    caddy, base, path, original, calls = shared_caddy
    caddy.preflight()
    path.write_bytes(original + b"# edited elsewhere\n")
    with pytest.raises(RuntimeError, match="live configuration"):
        caddy.apply(base, "new.example.com { respond added }\n")
    assert b"edited elsewhere" in path.read_bytes() and b"added" not in path.read_bytes()


class FakeAPI:
    def __init__(self, objects=False):
        self.items, self.calls = [], []
        self.objects = objects

    def request(self, path, data=None):
        self.calls.append((path, data))
        if path == "inbounds/list":
            return self.items
        if path == "server/getNewX25519Cert":
            return {"privateKey": "fixture-private-do-not-log", "publicKey": "fixture-public"}
        if path == "inbounds/add":
            item = {**data, "id": len(self.items) + 1}
            self.items.append(item)
            return item
        if path.startswith("inbounds/get/"):
            item = self.items[int(path.rsplit("/", 1)[1]) - 1]
            if self.objects:
                return {
                    **item,
                    "settings": json.loads(item["settings"]),
                    "streamSettings": json.loads(item["streamSettings"]),
                }
            return item


@pytest.mark.parametrize("object_response", [False, True])
def test_inbounds_export_only_public_key_and_tunnel_parameters(adaptive, capsys, object_response):
    deployment, base, _ = adaptive
    base.mkdir()
    deployment.context.node["deployment"]["inbounds"] = [
        {
            "name": "gb",
            "port": 8443,
            "listen": "127.0.0.1",
            "server_name": "example.com",
            "target_port": 443,
        }
    ]
    api = FakeAPI(object_response)
    provisioner = InboundProvisioner(deployment.context, api, deployment.host)
    provisioner.apply(base)
    exported = (base / "tunnel-connections.json").read_text()
    assert "fixture-private-do-not-log" not in exported
    assert "fixture-public" in exported and "127.0.0.1:8443" in exported
    client = json.loads(api.items[0]["settings"])["clients"][0]["id"]
    assert client in exported and client not in capsys.readouterr().out
    if os.name != "nt":
        assert (base / "tunnel-connections.json").stat().st_mode & 0o777 == 0o600
    provisioner.rollback()
    assert ("inbounds/del/1", {}) in api.calls


def test_inbound_conflict_does_not_rotate_an_existing_identity(adaptive):
    deployment, base, _ = adaptive
    deployment.context.node["deployment"]["inbounds"] = [
        {
            "name": "gb",
            "port": 8443,
            "listen": "127.0.0.1",
            "server_name": "example.com",
            "target_port": 443,
        }
    ]
    api = FakeAPI()
    api.items = [{"port": 8443, "settings": "existing-client-and-private-key"}]
    with pytest.raises(RuntimeError, match="not overwritten"):
        InboundProvisioner(deployment.context, api, deployment.host).apply(base)
    assert [path for path, _ in api.calls] == ["inbounds/list"]


def test_api_errors_do_not_expose_response_secrets(adaptive, monkeypatch):
    deployment, base, _ = adaptive
    api = PanelAPI(deployment.context, "fixture-token")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, limit):
            return b'{"success":false,"msg":"fixture-private-key"}'

    monkeypatch.setattr(api.opener, "open", lambda *a, **k: Response())
    with pytest.raises(RuntimeError) as error:
        api.request("inbounds/list")
    assert "fixture-private-key" not in str(error.value) and "fixture-token" not in str(error.value)


def test_preflight_detects_udp_occupancy(adaptive):
    deployment, _, _ = adaptive
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as occupied:
        occupied.bind(("127.0.0.1", 0))
        with pytest.raises(RuntimeError, match="occupied"):
            HostEnvironment.require_endpoint(
                deployment.host, occupied.getsockname()[1], "127.0.0.1"
            )


def test_native_restore_preserves_database_identities(adaptive, db_file, monkeypatch):
    deployment, base, calls = adaptive
    deployment.context.payload.update(
        action="restore", backup=base64.b64encode(db_file.read_bytes()).decode()
    )
    monkeypatch.setattr(
        deployment.context, "command", lambda args, **kwargs: calls.append(args) or ""
    )
    deployment.deploy(base)
    assert not any("setting" in call for call in calls)
    import sqlite3

    with sqlite3.connect(base / "db/x-ui.db") as db:
        assert db.execute("SELECT username FROM users").fetchone()[0] == "original-admin"
        assert (
            db.execute("SELECT stream_settings FROM inbounds").fetchone()[0]
            == "reality-private-key"
        )


def test_native_digest_failure_never_extracts_an_archive(adaptive, monkeypatch):
    from contextlib import nullcontext

    deployment, base, _ = adaptive
    base.mkdir()
    monkeypatch.setattr("app.agent.native_release.architecture", lambda: "amd64")
    monkeypatch.setattr(
        "app.agent.native_release.urllib.request.urlopen",
        lambda *a, **k: nullcontext(io.BytesIO(b"tampered archive")),
    )
    # Exercise the real installer rather than the deployment fixture's stub.
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        ORIGINAL_NATIVE_INSTALL(NativeRelease(deployment.context), base)
    assert not (base / "runtime").exists()

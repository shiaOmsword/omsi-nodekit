import json
import os
import socket
import sqlite3
import ssl
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient

from app.agent.adaptive_deployment import AdaptiveDeployment
from app.agent.caddy_reuse import ExistingCaddy
from app.agent.configure import ConfigureSubscriptions
from app.agent.context import AgentContext
from app.agent.database import PanelDatabase
from app.agent.discovery import SystemInventory
from app.agent.inbound_inventory import inbound_inventory
from app.agent.panel_api import InboundProvisioner
from app.agent.panels import PanelInspector
from app.agent.subscriptions import (
    SubscriptionDiagnostics,
    caddy_status,
    preflight_caddy_network,
    verify_caddy_upstream,
)
from app.container import build_container
from app.create_app import create_app
from app.entities import ExecutionEvent, Node
from app.ports import NodeExecutor
from framework.tasks import TaskScheduler
from tests.conftest import create_database
from tests.test_adaptive_deployment import FakeAPI


def complete_database(path):
    create_database(
        path,
        {
            "webPort": "2053",
            "webBasePath": "/nodekit/",
            "subEnable": "true",
            "subListen": "172.30.50.1",
            "subPort": "2097",
            "subPath": "/sub/",
            "subURI": "https://old.example.com/sub/",
        },
    )
    with sqlite3.connect(path) as db:
        for name, kind in (
            ("remark", "TEXT"),
            ("enable", "INTEGER"),
            ("listen", "TEXT"),
            ("port", "INTEGER"),
            ("protocol", "TEXT"),
        ):
            db.execute(f"ALTER TABLE inbounds ADD COLUMN {name} {kind}")
        db.execute(
            "UPDATE inbounds SET remark=?,enable=1,listen='0.0.0.0',port=8443,protocol='vless',settings=?,stream_settings=?",
            (
                "Manual inbound",
                json.dumps(
                    {
                        "clients": [
                            {
                                "email": "existing-client",
                                "enable": True,
                                "id": "private-client-uuid",
                                "subId": "private-sub-token",
                            }
                        ]
                    }
                ),
                json.dumps(
                    {
                        "network": "tcp",
                        "security": "reality",
                        "realitySettings": {"privateKey": "private-reality-key"},
                    }
                ),
            ),
        )
    return path


@pytest.fixture
def owned(tmp_path, node, settings, renderer, monkeypatch):
    data = node.export_config()
    data["caddy"].update(enabled=True, domain="old.example.com", https_port=443)
    data["deployment"] = {
        "panel_runtime": "docker",
        "caddy_mode": "existing",
        "caddy_id": "native:caddy",
        "subscription_bind": "127.0.0.1",
    }
    old_node = Node.model_validate(data)
    base = tmp_path / "test-node"
    (base / "db").mkdir(parents=True)
    database = complete_database(base / "db/x-ui.db")
    old_site = renderer.artifacts(old_node)["Caddyfile.site"]
    (base / "Caddyfile.site").write_text(old_site)
    (base / "compose.yaml").write_text(renderer.artifacts(old_node)["compose.yaml"])
    (base / "manifest.json").write_text(json.dumps({"node": old_node.export_config()}))
    (base / "subscriptions.json").write_text(
        json.dumps([{"name": "one", "url": "https://old.example.com/sub/private-sub-token"}])
    )
    shared = tmp_path / "SharedCaddyfile"
    shared.write_text("other.example.com { respond existing }\n\n" + old_site)
    data["caddy"].update(domain="new.example.com", https_port=2096)
    new_node = Node.model_validate(data)
    context = AgentContext(
        {
            "action": "configure",
            "node": new_node.export_config(),
            "files": renderer.artifacts(new_node),
            "runtime": {
                "deployment": settings.deployment.model_dump(),
                "limits": settings.limits.model_dump(),
            },
        }
    )
    finding = {"id": "docker:owned", "installation": "managed", "active": True}
    proxy = {
        "id": "native:caddy",
        "installation": "native",
        "active": True,
        "config_source": "file",
        "config_path": str(shared),
        "routes": [{"hosts": ["other.example.com"]}, {"hosts": ["old.example.com"]}],
    }
    inspector = SimpleNamespace(
        selected=finding, report={"caddy": [proxy]}, database=lambda: database
    )
    calls = []
    monkeypatch.setattr(context, "command", lambda args, **kwargs: calls.append(args) or "")
    monkeypatch.setattr(ExistingCaddy, "_live", lambda self: {})
    monkeypatch.setattr(ExistingCaddy, "_command", lambda self, args: calls.append(args) or "{}")
    monkeypatch.setattr("app.agent.configure.verify_caddy_upstream", lambda *args: None)
    host = SimpleNamespace(require_endpoint=lambda *args: None, port_open=lambda *args: True)
    operation = ConfigureSubscriptions(
        context, host, PanelDatabase(context), SimpleNamespace(check=lambda *args: None), inspector
    )
    return SimpleNamespace(
        operation=operation,
        base=base,
        database=database,
        shared=shared,
        context=context,
        calls=calls,
        inspector=inspector,
    )


def rows(path, table):
    with sqlite3.connect(path) as db:
        return db.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()


def test_discovery_reads_inbounds_without_secrets_or_writes(owned, monkeypatch):
    inventory = SystemInventory(owned.context)
    inspector = PanelInspector(inventory)
    finding = {"id": "managed:test-node"}
    before = owned.database.read_bytes()
    inspector._settings(finding, owned.database, lambda path: None)
    assert finding["inbounds_readable"]
    inbound = finding["inbounds"][0]
    assert inbound["port"] == 8443 and inbound["security"] == "reality"
    assert inbound["clients"] == [
        {"email": "existing-client", "enabled": True, "has_subscription": True}
    ]
    assert "private-" not in json.dumps(finding)
    assert inspector.probe_ids[finding["id"]] == "private-sub-token"
    assert owned.database.read_bytes() == before


def test_inventory_bounds_large_json_before_reading_it(owned):
    with sqlite3.connect(owned.database) as db:
        db.execute("UPDATE inbounds SET settings=?", ("x" * 10000,))
        items, probe_id, truncated = inbound_inventory(db, 2048)
    assert items == [] and probe_id is None and truncated


def test_configure_preserves_clients_other_sites_and_updates_public_url(owned, capsys):
    clients = rows(owned.database, "inbounds")
    owned.operation.apply(owned.base)
    assert rows(owned.database, "inbounds") == clients
    with sqlite3.connect(owned.database) as db:
        actual = dict(db.execute("SELECT key,value FROM settings"))
    assert actual["subURI"] == "https://new.example.com:2096/sub/"
    assert actual["subListen"] == "127.0.0.1"
    assert owned.shared.read_text().startswith("other.example.com { respond existing }")
    assert "old.example.com" not in owned.shared.read_text()
    assert "new.example.com:2096" in owned.shared.read_text()
    assert (owned.base / "Caddyfile.site").read_text() in owned.shared.read_text()
    assert list(owned.base.glob("before-configure-*.db"))
    assert (
        "new.example.com:2096/sub/private-sub-token"
        in (owned.base / "subscriptions.json").read_text()
    )
    assert "private-sub-token" not in capsys.readouterr().out
    assert all(
        "shared-caddy" not in call for call in owned.calls if "stop" in call or "start" in call
    )


@pytest.mark.parametrize("stage", ["upstream", "reload"])
def test_configure_failure_restores_settings_site_and_manifest(owned, monkeypatch, stage):
    before_settings, before_clients = (
        rows(owned.database, "settings"),
        rows(owned.database, "inbounds"),
    )
    before_site = owned.shared.read_bytes()
    before_manifest = (owned.base / "manifest.json").read_bytes()
    if stage == "upstream":

        def fail(*args):
            raise RuntimeError("fixture upstream unreachable")

        monkeypatch.setattr("app.agent.configure.verify_caddy_upstream", fail)
    else:

        def command(self, args):
            if "reload" in args and "new.example.com" in owned.shared.read_text():
                raise RuntimeError("fixture reload failed")
            return "{}"

        monkeypatch.setattr(ExistingCaddy, "_command", command)
    with pytest.raises(RuntimeError):
        owned.operation.apply(owned.base)
    # Row IDs are not settings identities; values and missing keys must be restored exactly.
    assert {(row[1], row[2]) for row in rows(owned.database, "settings")} == {
        (row[1], row[2]) for row in before_settings
    }
    assert rows(owned.database, "inbounds") == before_clients
    assert owned.shared.read_bytes() == before_site
    assert (owned.base / "manifest.json").read_bytes() == before_manifest
    assert sum("start" in call for call in owned.calls) == 2


def test_modified_owned_site_is_rejected_before_stopping_panel(owned):
    owned.shared.write_text(
        owned.shared.read_text().replace("old.example.com", "edited.example.com")
    )
    with pytest.raises(RuntimeError, match="original manifest"):
        owned.operation.apply(owned.base)
    assert not any("stop" in call for call in owned.calls)
    assert not list(owned.base.glob("before-configure-*.db"))


def test_unpublished_2096_is_rejected_before_caddy_or_panel_mutations(owned):
    context, inspector = owned.context, owned.inspector
    context.node["deployment"].update(caddy_id="docker:abc", subscription_bind="172.30.50.1")
    inspector.report["caddy"][0].update(
        id="docker:abc",
        installation="docker",
        network_mode="shared-proxy",
        host_gateway="172.30.50.1",
        config_path="/etc/caddy/Caddyfile",
        published_ports=["0.0.0.0:443->443/tcp"],
    )
    inspector.inventory = SimpleNamespace(
        containers=lambda: [
            {
                "Id": "abc",
                "Mounts": [{"Source": str(owned.shared), "Destination": "/etc/caddy/Caddyfile"}],
            }
        ]
    )
    with pytest.raises(RuntimeError, match="2096:2096"):
        owned.operation.apply(owned.base)
    assert owned.calls == []


def test_fresh_verifies_caddy_namespace_not_just_host_socket(owned, monkeypatch):
    monkeypatch.setattr("app.agent.subscriptions.caddy_status", lambda *args: None)
    with pytest.raises(RuntimeError, match="firewall"):
        verify_caddy_upstream(owned.context, owned.inspector.report["caddy"][0])
    monkeypatch.setattr("app.agent.subscriptions.caddy_status", lambda *args: 404)
    verify_caddy_upstream(owned.context, owned.inspector.report["caddy"][0])


def test_network_preflight_uses_and_releases_the_actual_subscription_port(owned):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    owned.context.node["panel"]["subscription_port"] = port
    preflight_caddy_network(owned.context, {"installation": "native"})
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", port))


def test_blocked_bridge_preflight_does_not_install_or_create_target(owned, monkeypatch):
    owned.context.payload["action"] = "fresh"
    owned.inspector.report.update(panels=[], warnings=[], capabilities={"systemctl": True})

    def blocked(*args):
        raise RuntimeError("fixture bridge blocked")

    monkeypatch.setattr("app.agent.adaptive_deployment.preflight_caddy_network", blocked)
    operation = AdaptiveDeployment(
        owned.context,
        owned.operation.host,
        owned.operation.database,
        owned.operation.diagnostics,
        owned.inspector,
    )
    destination = owned.base / "fresh-target"
    with pytest.raises(RuntimeError, match="bridge blocked"):
        operation.deploy(destination)
    assert not destination.exists()
    assert not any("stop" in call or "pull" in call or "install" in call for call in owned.calls)


def test_configure_waits_for_subscription_listener_after_admin_is_ready(owned, monkeypatch):
    attempts = []

    def opened(port, address="127.0.0.1"):
        if port == owned.context.node["panel"]["subscription_port"]:
            attempts.append(port)
            return len(attempts) >= 3
        return True

    monkeypatch.setattr(owned.operation.host, "port_open", opened)
    monkeypatch.setattr("app.agent.configure.time.sleep", lambda *args: None)
    owned.operation._ready()
    assert len(attempts) == 3


def test_wget_http_404_and_transport_failure_are_distinguished(owned, monkeypatch):
    proxy = {"id": "docker:abc", "installation": "docker"}
    response = SimpleNamespace(returncode=1, stderr="HTTP/1.1 404 Not Found\nsecret URL", stdout="")
    monkeypatch.setattr(owned.context.runner, "completed", lambda *a, **k: response)
    assert caddy_status(owned.context, proxy, "172.30.50.1", 2097, "/sub/private-sub-token") == 404
    response.stderr = "wget: connection timed out; private-sub-token"
    assert caddy_status(owned.context, proxy, "172.30.50.1", 2097, "/sub/private-sub-token") is None


def test_named_first_client_has_subscription_and_repeat_apply_is_idempotent(owned, capsys):
    context = owned.context
    context.node["deployment"]["inbounds"] = [
        {
            "name": "first",
            "listen": "127.0.0.1",
            "port": 8444,
            "server_name": "example.com",
            "target_port": 443,
            "client_email": "my-client",
        }
    ]
    api = FakeAPI()
    provisioner = InboundProvisioner(context, api, owned.operation.host)
    provisioner.apply(owned.base)
    client = json.loads(api.items[0]["settings"])["clients"][0]
    assert client["email"] == "my-client" and len(client["subId"]) >= 24
    assert client["subId"] in (owned.base / "subscriptions.json").read_text()
    assert client["subId"] not in capsys.readouterr().out
    previous = (owned.base / "subscriptions.json").read_bytes()
    InboundProvisioner(context, api, owned.operation.host).apply(owned.base, allow_existing=True)
    assert len(api.items) == 1 and (owned.base / "subscriptions.json").read_bytes() == previous
    if os.name != "nt":
        assert (owned.base / "subscriptions.json").stat().st_mode & 0o777 == 0o600


def diagnostic(owned):
    finding = {
        "id": "docker:owned",
        "installation": "managed",
        "active": True,
        "network_mode": "host",
        "settings": {
            "subEnable": "true",
            "subListen": "172.30.50.1",
            "subPort": "2097",
            "subPath": "/sub/",
            "subURI": "https://new.example.com:2096/sub/",
        },
    }
    proxy = {"id": "native:caddy", "installation": "native", "routes": [], "published_ports": []}
    inspector = SimpleNamespace(
        selected=finding,
        report={"caddy": [proxy]},
        panels=SimpleNamespace(probe_ids={finding["id"]: "private-sub-token"}),
    )
    return inspector, SubscriptionDiagnostics(owned.context, inspector)


def test_diagnostic_exposes_failing_hop_without_subscription_token(owned, monkeypatch, capsys):
    inspector, check = diagnostic(owned)
    monkeypatch.setattr("app.agent.subscriptions.http_status", lambda *a, **k: 200)
    monkeypatch.setattr("app.agent.subscriptions.caddy_status", lambda *a, **k: None)
    assert check.check()
    states = {c["name"]: c["state"] for c in inspector.report["subscription_checks"]}
    assert states["upstream"] == "ok" and states["caddy_upstream"] == "error"
    assert "private-sub-token" not in json.dumps(inspector.report) + capsys.readouterr().out


def test_public_tls_failure_is_reported_without_insecure_retry(owned, monkeypatch):
    inspector, check = diagnostic(owned)
    calls = []

    def status(*args, **kwargs):
        calls.append(kwargs)
        if kwargs.get("tls"):
            raise ssl.SSLCertVerificationError()
        return 200

    monkeypatch.setattr("app.agent.subscriptions.http_status", status)
    monkeypatch.setattr("app.agent.subscriptions.caddy_status", lambda *a, **k: 200)
    check.check()
    assert [c for c in inspector.report["subscription_checks"] if c["name"] == "https"][0][
        "state"
    ] == "error"
    assert sum(call.get("tls", False) for call in calls) == 1


def test_configure_api_preview_revision_and_explicit_launch(settings, owned):
    calls = []

    class FakeExecutor(NodeExecutor):
        def execute(self, node, action, backup):
            calls.append(str(action))
            yield ExecutionEvent(message="fixture configured without SSH")

    container = build_container(settings, overrides={NodeExecutor: FakeExecutor()})
    with TestClient(
        create_app(settings, container=container),
        base_url="http://127.0.0.1:8765",
        headers={"X-Nodekit-Request": "1"},
    ) as client:
        text = yaml.safe_dump(owned.context.node)
        saved = client.put("/api/nodes/test-node", json={"yaml": text}).json()["data"]
        response = client.get("/api/nodes/test-node/plan?action=configure")
        assert response.status_code == 200
        plan = response.json()["data"]
        assert set(plan["files"]) == {"Caddyfile.site", "deployment.json"}
        assert not client.get("/api/jobs").json()["data"] and calls == []
        client.put("/api/nodes/test-node", json={"yaml": text + "\n# changed\n"})
        stale = client.post(
            "/api/nodes/test-node/jobs", json={"action": "configure", "revision": saved["revision"]}
        )
        assert stale.status_code == 409 and calls == []
        revision = client.get("/api/nodes/test-node/plan?action=configure").json()["data"][
            "revision"
        ]
        started = client.post(
            "/api/nodes/test-node/jobs", json={"action": "configure", "revision": revision}
        )
        assert started.status_code == 202
        container.resolve(TaskScheduler).close()
        assert calls == ["configure"]
        assert (
            client.get("/api/jobs/" + started.json()["data"]["id"]).json()["data"]["status"]
            == "succeeded"
        )

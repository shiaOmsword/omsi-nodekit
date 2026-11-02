import json
import os
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient

from app.agent.attach_caddy import attachment_status
from app.agent.caddy_config import standalone_config
from app.agent.caddy_reuse import ExistingCaddy
from app.container import build_container
from app.create_app import create_app
from app.entities import ExecutionEvent
from app.ports import NodeExecutor
from framework.tasks import TaskScheduler
from tests.test_subscriptions import owned as owned
from tests.test_subscriptions import rows

# Golden bytes produced before PR #31, independent of the current renderer.
# The interpolation of the site (already ending in LF) added a second final LF.
LEGACY_STANDALONE = b"""{
    admin off
}

https://old.example.com:443 {
    tls {
        issuer acme {
            disable_tlsalpn_challenge
        }
    }
    @subscriptions path /sub/*
    handle @subscriptions {
        reverse_proxy 127.0.0.1:2097
    }
    handle {
        respond 404
    }
}

"""


@pytest.fixture
def attaching(owned, monkeypatch):
    old = json.loads((owned.base / "manifest.json").read_text())["node"]
    old["deployment"].update(caddy_mode="docker", caddy_id=None)
    (owned.base / "manifest.json").write_text(json.dumps({"node": old}))
    # This fixture represents a remote Linux-generated file, including on Windows.
    (owned.base / "Caddyfile").write_bytes(standalone_config(old).encode())
    (owned.base / "Caddyfile.site").unlink()
    owned.shared.write_text("other.example.com { respond existing }\n")
    owned.inspector.report["caddy"][0]["routes"] = [{"hosts": ["other.example.com"]}]
    owned.inspector.selected["settings"] = {"webPort": "2053", "webBasePath": "/nodekit/"}
    owned.inspector.selected.update(container="owned-panel", image=old["panel"]["image"])
    owned.context.payload["action"] = "attach_caddy"
    monkeypatch.setattr(owned.context, "directory", lambda: owned.base)
    return owned


@pytest.mark.parametrize("old_mode", ["none", "docker"])
@pytest.mark.parametrize("runtime", ["native", "docker"])
def test_attach_preserves_database_clients_other_sites_then_allows_configure(
    attaching, old_mode, runtime, capsys
):
    old = json.loads((attaching.base / "manifest.json").read_text())
    old["node"]["deployment"].update(caddy_mode=old_mode, panel_runtime=runtime)
    attaching.context.node["deployment"]["panel_runtime"] = runtime
    if runtime == "native":
        attaching.inspector.selected.update(container=None, service=attaching.context.unit("panel"))
    (attaching.base / "manifest.json").write_text(json.dumps(old))
    clients, users = rows(attaching.database, "inbounds"), rows(attaching.database, "users")
    old_caddy = (attaching.base / "Caddyfile").read_bytes()
    assert attachment_status(attaching.context) == "required"
    attaching.operation.apply(attaching.base)
    saved = json.loads((attaching.base / "manifest.json").read_text())
    assert saved["action"] == "attach_caddy"
    assert saved["node"]["deployment"]["caddy_mode"] == "existing"
    assert attachment_status(attaching.context) == "ready"
    assert attaching.shared.read_text().startswith("other.example.com { respond existing }")
    assert (attaching.base / "Caddyfile.site").read_text() in attaching.shared.read_text()
    assert (attaching.base / "Caddyfile").read_bytes() == old_caddy
    assert rows(attaching.database, "inbounds") == clients
    assert rows(attaching.database, "users") == users
    assert list(attaching.base.glob("before-configure-*.db"))
    assert not any("restart" in call for call in attaching.calls)
    attaching.context.payload["action"] = "configure"
    attaching.operation.apply(attaching.base)
    assert attaching.shared.read_text().count("https://new.example.com:2096") == 1
    assert "private-" not in capsys.readouterr().out


@pytest.mark.parametrize("stage", ["upstream", "reload", "commit"])
def test_attach_failure_restores_settings_and_leaves_no_fake_shared_ownership(
    attaching, monkeypatch, stage
):
    before = {p: p.read_bytes() for p in attaching.base.iterdir() if p.is_file()}
    before_settings = {(r[1], r[2]) for r in rows(attaching.database, "settings")}
    before_site = attaching.shared.read_bytes()

    def fail(*args):
        raise RuntimeError("fixture failure")

    if stage == "upstream":
        monkeypatch.setattr("app.agent.configure.verify_caddy_upstream", fail)
    elif stage == "commit":
        monkeypatch.setattr("app.agent.configure.NodeNetwork.commit", fail)
    else:

        def command(self, args):
            if "reload" in args and "new.example.com" in attaching.shared.read_text():
                fail()
            return "{}"

        monkeypatch.setattr(ExistingCaddy, "_command", command)
    with pytest.raises(RuntimeError):
        attaching.operation.apply(attaching.base)
    assert {(r[1], r[2]) for r in rows(attaching.database, "settings")} == before_settings
    assert attaching.shared.read_bytes() == before_site
    assert not (attaching.base / "Caddyfile.site").exists()
    assert not (attaching.base / "deployment.json").exists()
    assert attachment_status(attaching.context) == "required"
    assert all(p.read_bytes() == content for p, content in before.items())


@pytest.mark.parametrize(
    "conflict",
    [
        "runtime",
        "image",
        "port",
        "base_path",
        "subscription_path",
        "tunnels",
        "database",
        "inactive",
        "existing-site",
        "routes",
        "host",
    ],
)
def test_attach_refuses_conflicts_before_any_service_changes(attaching, conflict, tmp_path):
    node = attaching.context.node
    if conflict == "runtime":
        node["deployment"]["panel_runtime"] = "native"
    elif conflict in {"image", "base_path", "subscription_path"}:
        node["panel"][conflict] += "changed"
    elif conflict == "port":
        node["panel"]["port"] += 1
    elif conflict == "tunnels":
        node["tunnels"] = [{"name": "changed"}]
    elif conflict == "database":
        attaching.inspector.database = lambda: tmp_path / "foreign.db"
    elif conflict == "inactive":
        attaching.inspector.selected["active"] = False
    elif conflict == "existing-site":
        (attaching.base / "Caddyfile.site").write_text("foreign")
    elif conflict == "routes":
        (attaching.base / "xhttp-routes.json").write_text('[{"id": 1}]')
    elif conflict == "host":
        attaching.inspector.report["caddy"][0]["routes"].append({"hosts": ["*.example.com"]})
    before = attaching.database.read_bytes()
    with pytest.raises(RuntimeError):
        attaching.operation.apply(attaching.base)
    assert attaching.database.read_bytes() == before
    assert not any("stop" in call or "start" in call for call in attaching.calls)


def owned_caddy(attaching):
    node = attaching.context.node
    node["deployment"].update(caddy_id="docker:owned-caddy", subscription_bind="127.0.0.1")
    source = attaching.base / "Caddyfile"
    container = {
        "Id": "owned-caddy",
        "Config": {
            "Image": json.loads((attaching.base / "manifest.json").read_text())["node"]["caddy"][
                "image"
            ],
            "Cmd": ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"],
            "Labels": {
                "com.docker.compose.project": attaching.context.project(),
                "com.docker.compose.service": "caddy",
            },
        },
        "HostConfig": {"NetworkMode": "host"},
        "Mounts": [{"Source": str(source), "Destination": "/etc/caddy/Caddyfile"}],
    }
    attaching.inspector.inventory = SimpleNamespace(containers=lambda: [container])
    attaching.inspector.report["caddy"] = [
        {
            "id": "docker:owned-caddy",
            "installation": "docker",
            "active": True,
            "network_mode": "host",
            "config_source": "file",
            "config_path": "/etc/caddy/Caddyfile",
            "routes": [{"hosts": ["old.example.com"], "listen": [":443"]}],
        }
    ]
    return source, container


def test_promotes_pristine_owned_docker_caddy_then_supports_shared_reload(attaching):
    source, _ = owned_caddy(attaching)
    inode = source.stat().st_ino
    attaching.operation.apply(attaching.base)
    assert source.stat().st_ino == inode
    assert "admin 127.0.0.1:2019" in source.read_text()
    assert "old.example.com" not in source.read_text()
    assert (attaching.base / "Caddyfile.site").read_text() in source.read_text()
    assert [c for c in attaching.calls if "restart" in c] == [["docker", "restart", "owned-caddy"]]
    assert attachment_status(attaching.context) == "ready"
    attaching.context.payload["action"] = "configure"
    attaching.inspector.report["caddy"][0]["routes"] = [
        {"hosts": ["new.example.com"], "listen": [":2096"]}
    ]
    attaching.operation.apply(attaching.base)
    assert source.read_text().count("https://new.example.com:2096") == 1


@pytest.mark.parametrize("original", [LEGACY_STANDALONE, LEGACY_STANDALONE[:-1]])
def test_promotes_both_original_and_transitional_generated_caddyfiles(attaching, original):
    source, _ = owned_caddy(attaching)
    source.write_bytes(original)
    attaching.operation.apply(attaching.base)
    assert "admin 127.0.0.1:2019" in source.read_text()
    assert attachment_status(attaching.context) == "ready"
    backup = next(attaching.base.glob("Caddyfile.before-attach-*"))
    assert backup.read_bytes() == original


def test_renderer_preserves_the_original_standalone_bytes(attaching):
    saved = json.loads((attaching.base / "manifest.json").read_text())["node"]
    assert standalone_config(saved).encode() == LEGACY_STANDALONE


@pytest.mark.parametrize("stage", ["validate", "restart", "commit"])
def test_owned_caddy_failure_restores_original_config_and_manifest(attaching, monkeypatch, stage):
    source, _ = owned_caddy(attaching)
    original = source.read_bytes()
    manifest = (attaching.base / "manifest.json").read_bytes()

    def command(self, args):
        if stage == "validate" and "validate" in args and source.read_bytes() != original:
            raise RuntimeError("fixture invalid config")
        return "{}"

    monkeypatch.setattr(ExistingCaddy, "_command", command)
    if stage == "restart":

        def run(args, **kwargs):
            attaching.calls.append(args)
            if "restart" in args and source.read_bytes() != original:
                raise RuntimeError("fixture restart failure")
            return ""

        monkeypatch.setattr(attaching.context, "command", run)
    elif stage == "commit":

        def fail(*args):
            raise RuntimeError("fixture network failure")

        monkeypatch.setattr("app.agent.configure.NodeNetwork.commit", fail)
    with pytest.raises(RuntimeError):
        attaching.operation.apply(attaching.base)
    assert source.read_bytes() == original
    assert (attaching.base / "manifest.json").read_bytes() == manifest
    assert not (attaching.base / "Caddyfile.site").exists()
    restarts = [c for c in attaching.calls if c == ["docker", "restart", "owned-caddy"]]
    assert len(restarts) == (0 if stage == "validate" else 2)


@pytest.mark.parametrize(
    "conflict",
    ["edited-file", "extra-newline", "changed-backend", "foreign-label", "bridge", "command"],
)
def test_never_promotes_modified_or_foreign_standalone_caddy(attaching, conflict):
    source, container = owned_caddy(attaching)
    if conflict == "edited-file":
        source.write_text(source.read_text() + "\nother.example.com { respond custom }\n")
    elif conflict == "extra-newline":
        source.write_bytes(source.read_bytes() + b"\n")
    elif conflict == "changed-backend":
        source.write_bytes(source.read_bytes().replace(b"127.0.0.1:2097", b"127.0.0.1:2098"))
    elif conflict == "foreign-label":
        container["Config"]["Labels"]["com.docker.compose.project"] = "foreign"
    elif conflict == "bridge":
        container["HostConfig"]["NetworkMode"] = "bridge"
    else:
        container["Config"]["Cmd"] += ["--resume"]
    before = source.read_bytes()
    with pytest.raises(RuntimeError, match="Caddy attachment requires"):
        attaching.operation.apply(attaching.base)
    assert source.read_bytes() == before
    assert not any("stop" in c or "restart" in c for c in attaching.calls)


def test_normal_configure_directs_unattached_panel_to_explicit_operation(attaching):
    attaching.context.payload["action"] = "configure"
    with pytest.raises(RuntimeError, match="run Attach Caddy"):
        attaching.operation.apply(attaching.base)
    assert attaching.calls == []


def test_attach_preview_is_read_only_and_launch_rejects_stale_revision(settings, attaching):
    calls = []

    class Executor(NodeExecutor):
        def execute(self, node, action, backup):
            calls.append(str(action))
            yield ExecutionEvent(message="fixture attached")

    container = build_container(settings, overrides={NodeExecutor: Executor()})
    with TestClient(
        create_app(settings, container=container),
        base_url="http://127.0.0.1:8765",
        headers={"X-Nodekit-Request": "1"},
    ) as client:
        config = yaml.safe_dump(attaching.context.node)
        client.put("/api/nodes/test-node", json={"yaml": config})
        response = client.get("/api/nodes/test-node/plan?action=attach_caddy")
        assert response.status_code == 200
        plan = response.json()["data"]
        assert set(plan["files"]) == {"Caddyfile.site", "deployment.json"}
        assert any("restarting only that owned container" in s for s in plan["steps"])
        assert calls == []
        client.put("/api/nodes/test-node", json={"yaml": config + "\n# changed\n"})
        stale = client.post(
            "/api/nodes/test-node/jobs",
            json={"action": "attach_caddy", "revision": plan["revision"]},
        )
        assert stale.status_code == 409
        fresh = client.get("/api/nodes/test-node/plan?action=attach_caddy").json()["data"]
        response = client.post(
            "/api/nodes/test-node/jobs",
            json={"action": "attach_caddy", "revision": fresh["revision"]},
        )
        assert response.status_code == 202
        container.resolve(TaskScheduler).close()
        assert calls == ["attach_caddy"]


@pytest.mark.skipif(os.name == "nt", reason="symlinks require elevated Windows privileges")
def test_attachment_rejects_symlink_metadata(attaching, tmp_path):
    path = attaching.base / "manifest.json"
    foreign = tmp_path / "foreign.json"
    path.rename(foreign)
    path.symlink_to(foreign)
    assert attachment_status(attaching.context) == "unknown"
    with pytest.raises(RuntimeError):
        attaching.operation.apply(attaching.base)
    assert attaching.calls == []


@pytest.mark.parametrize("variant", ["entrypoint", "implicit-adapter"])
def test_owned_docker_command_variants(attaching, variant):
    source, container = owned_caddy(attaching)
    if variant == "entrypoint":
        container["Config"]["Entrypoint"] = ["caddy"]
        container["Config"]["Cmd"] = container["Config"]["Cmd"][1:]
    else:
        container["Config"]["Cmd"] = container["Config"]["Cmd"][:-2]
    attaching.operation.apply(attaching.base)
    assert "admin 127.0.0.1:2019" in source.read_text()


def test_attach_then_create_xhttp_preserves_old_clients_and_shared_site(
    attaching, monkeypatch, capsys
):
    import copy

    from app.agent.xhttp_manager import XHTTPManager

    attaching.operation.apply(attaching.base)
    clients = rows(attaching.database, "inbounds")
    context = attaching.context
    context.payload["action"] = "xhttp"
    context.payload["options"] = {
        "xhttp": {
            "operation": "create",
            "remark": "phone",
            "domain": "vpn.example.com",
            "port": 10080,
            "path": "/xhttp-phone/",
            "mode": "auto",
            "client_email": "first",
        }
    }
    items = {}

    def request(path, data=None):
        if path == "inbounds/list":
            return copy.deepcopy(list(items.values()))
        if path == "inbounds/add":
            items[2] = {**copy.deepcopy(data), "id": 2, "tag": "in-10080-tcp"}
            return {"id": 2}
        if path == "inbounds/get/2":
            return copy.deepcopy(items[2])
        if path == "server/restartXrayService":
            return None
        raise AssertionError(path)

    monkeypatch.setattr(
        "app.agent.xhttp_manager.managed_api", lambda *args: SimpleNamespace(request=request)
    )
    XHTTPManager(
        context, attaching.operation.host, attaching.operation.database, attaching.inspector
    ).apply(attaching.base)
    assert items[2]["listen"] == "127.0.0.1"
    assert json.loads(items[2]["streamSettings"])["network"] == "xhttp"
    assert "reverse_proxy h2c://127.0.0.1:10080" in attaching.shared.read_text()
    assert "other.example.com { respond existing }" in attaching.shared.read_text()
    assert "https://new.example.com:2096" in attaching.shared.read_text()
    assert rows(attaching.database, "inbounds") == clients
    assert (attaching.base / "xhttp-routes.json").is_file()
    assert "private-" not in capsys.readouterr().out

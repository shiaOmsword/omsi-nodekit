import base64
import json
import shutil
import sqlite3
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app.agent.caddy import CaddyInspector
from app.agent.certificates import CertificateInspector
from app.agent.context import AgentContext
from app.agent.discovery import SystemInventory
from app.agent.existing_diagnostics import ExistingDiagnostics
from app.agent.host import HostEnvironment
from app.agent.inspection import InstallationInspector
from app.agent.panels import PanelInspector
from app.entities import ExecutionEvent, InstallationReport, Job, JobAction, Node, StoredNode
from app.ports import JobRepository, NodeRepository
from framework.entities import ValidationError
from tests.conftest import create_database


@pytest.fixture
def context(node, settings):
    return AgentContext(
        {
            "node": node.model_dump(mode="json"),
            "action": "check",
            "files": {},
            "runtime": {
                "deployment": settings.deployment.model_dump(),
                "limits": settings.limits.model_dump(),
                "discovery": {**settings.discovery.model_dump(), "native_environment_files": []},
            },
        }
    )


def native_panel(context, tmp_path, monkeypatch, settings=None):
    path = create_database(tmp_path / "native.db", settings)
    context.node["panel"].update(installation="native", database_path=str(path))
    inventory = SystemInventory(context)
    monkeypatch.setattr(
        inventory, "service", lambda name: {"ActiveState": "active"} if name == "x-ui" else {}
    )
    return inventory, path


def docker_panel(tmp_path, *, identifier="abc", name="panel", managed=False):
    folder = tmp_path / identifier
    folder.mkdir()
    create_database(
        folder / "x-ui.db", {"webPort": "2053", "webBasePath": "/secret/", "subEnable": "false"}
    )
    return {
        "Id": identifier,
        "Name": f"/{name}",
        "State": {"Running": True, "Pid": 0},
        "Config": {
            "Image": "ghcr.io/mhsanaei/3x-ui:3.11.0",
            "Env": ["SECRET=do-not-return"],
            "Labels": {
                "com.docker.compose.project": "omsi-test-node",
                "com.docker.compose.service": "panel",
            }
            if managed
            else {},
        },
        "Mounts": [{"Destination": "/etc/x-ui", "Source": str(folder)}],
        "HostConfig": {"NetworkMode": "bridge"},
        "NetworkSettings": {
            "Networks": {"proxy_net": {}},
            "Ports": {"2053/tcp": [{"HostIp": "127.0.0.1", "HostPort": "32053"}]},
        },
    }


def test_native_settings_are_read_only_and_whitelisted(context, tmp_path, monkeypatch):
    inventory, database = native_panel(
        context,
        tmp_path,
        monkeypatch,
        {
            "webPort": "8443",
            "webBasePath": "/panel/",
            "webCertFile": "/missing/cert.pem",
            "webKeyFile": "/missing/key.pem",
            "secret": "SESSION-SECRET",
            "tgBotToken": "TOKEN-SECRET",
            "xrayTemplateConfig": "REALITY-SECRET",
        },
    )
    before = database.read_bytes()
    panels = PanelInspector(inventory)
    findings = panels.discover([])
    selected = panels.select(findings)
    assert selected["installation"] == "native"
    assert selected["settings"]["webPort"] == "8443"
    assert selected["certificates"][0]["state"] == "missing"
    serialized = json.dumps(findings)
    assert "SECRET" not in serialized
    assert database.read_bytes() == before
    assert panels.database(selected) == database


def test_docker_database_mount_networks_and_explicit_selection(context, tmp_path, monkeypatch):
    inventory = SystemInventory(context)
    monkeypatch.setattr(inventory, "service", lambda _: {})
    context.node["panel"].update(installation="docker", container="second")
    first = docker_panel(tmp_path, identifier="one", name="first")
    second = docker_panel(tmp_path, identifier="two", name="second")
    panels = PanelInspector(inventory)
    findings = panels.discover([first, second])
    selected = panels.select(findings)
    assert selected["container"] == "second"
    assert selected["networks"] == ["proxy_net"]
    assert selected["published_ports"] == ["127.0.0.1:32053->2053/tcp"]
    assert panels.database(selected) == tmp_path / "two/x-ui.db"
    assert "do-not-return" not in json.dumps(findings)


def test_auto_never_guesses_between_multiple_panels(context, tmp_path, monkeypatch):
    context.node["panel"]["installation"] = "auto"
    inventory = SystemInventory(context)
    monkeypatch.setattr(inventory, "service", lambda _: {})
    panels = PanelInspector(inventory)
    findings = panels.discover(
        [docker_panel(tmp_path, identifier="one"), docker_panel(tmp_path, identifier="two")]
    )
    assert panels.select(findings) is None
    with pytest.raises(RuntimeError, match="unambiguous"):
        panels.database(None)


def test_postgres_is_reported_without_reading_sqlite(context, tmp_path, monkeypatch):
    inventory, _ = native_panel(context, tmp_path, monkeypatch)
    monkeypatch.setattr(inventory, "environment", lambda *a: {"XUI_DB_TYPE": "postgres"})
    panels = PanelInspector(inventory)
    findings = panels.discover([])
    assert findings[0]["settings"] == {}
    assert "non-SQLite" in findings[0]["warnings"][0]
    with pytest.raises(RuntimeError):
        panels.database(findings[0])


def test_native_environment_is_not_executed_and_only_db_fields_survive(context, tmp_path):
    path = tmp_path / "environment"
    path.write_text(
        'XUI_DB_FOLDER="/srv/panel data"\nexport XUI_DB_TYPE=sqlite\nTOKEN=secret\nDANGEROUS=$(touch /tmp/do-not-run)\n'
    )
    result = SystemInventory(context).environment({}, [str(path)])
    assert result == {"XUI_DB_FOLDER": "/srv/panel data", "XUI_DB_TYPE": "sqlite"}


def test_caddy_summary_excludes_sensitive_config(context, tmp_path, monkeypatch):
    path = tmp_path / "caddy.json"
    path.write_text(
        json.dumps(
            {
                "apps": {
                    "http": {
                        "servers": {
                            "public": {
                                "listen": [":2096"],
                                "routes": [
                                    {
                                        "match": [{"host": ["vpn.example.com"]}],
                                        "handle": [
                                            {
                                                "handler": "subroute",
                                                "routes": [
                                                    {
                                                        "match": [{"path": ["/sub/*"]}],
                                                        "handle": [
                                                            {
                                                                "handler": "reverse_proxy",
                                                                "upstreams": [
                                                                    {"dial": "127.0.0.1:2097"}
                                                                ],
                                                                "headers": {
                                                                    "request": {
                                                                        "set": {
                                                                            "Authorization": [
                                                                                "SECRET-HEADER"
                                                                            ]
                                                                        }
                                                                    }
                                                                },
                                                            }
                                                        ],
                                                    }
                                                ],
                                            }
                                        ],
                                    }
                                ],
                            }
                        }
                    }
                },
                "storage": {"secret": "SECRET-STORAGE"},
            }
        )
    )
    context.node["caddy"]["config_path"] = str(path)
    inventory = SystemInventory(context)
    monkeypatch.setattr(
        inventory, "service", lambda _: {"ActiveState": "active", "ExecStart": "caddy run"}
    )
    findings = CaddyInspector(inventory).discover([])
    assert findings[0]["routes"] == [
        {
            "listen": [":2096"],
            "hosts": ["vpn.example.com"],
            "paths": ["/sub/*"],
            "upstreams": ["127.0.0.1:2097"],
        }
    ]
    assert "SECRET" not in json.dumps(findings)
    assert findings[0]["config_source"] == "file"


def test_caddy_container_adaptation_never_reloads_or_validates(context, monkeypatch):
    inventory = SystemInventory(context)
    monkeypatch.setattr(inventory, "service", lambda _: {})
    commands = []

    def command(args):
        commands.append(args)
        return '{"apps":{}}'

    monkeypatch.setattr(inventory, "command", command)
    container = {
        "Id": "caddy-id",
        "Name": "/caddy",
        "State": {"Running": True},
        "Config": {"Image": "caddy:2", "Cmd": ["caddy", "run", "--config", "/etc/caddy/Caddyfile"]},
        "HostConfig": {"NetworkMode": "proxy_net"},
        "NetworkSettings": {"Networks": {"proxy_net": {}}},
    }
    findings = CaddyInspector(inventory).discover([container])
    assert commands == [
        [
            "docker",
            "exec",
            "caddy-id",
            "caddy",
            "adapt",
            "--config",
            "/etc/caddy/Caddyfile",
            "--adapter",
            "caddyfile",
        ]
    ]
    assert findings[0]["networks"] == ["proxy_net"]
    assert "loopback" in findings[0]["warnings"][-1]


def test_discovery_without_docker_and_empty_server_succeeds(context, monkeypatch, capsys):
    monkeypatch.setattr(shutil, "which", lambda _: None)
    report = InstallationInspector(context).inspect()
    assert report["panels"] == report["caddy"] == []
    assert report["capabilities"]["compose"] is False
    assert InstallationReport.model_validate(report)
    assert '"report"' in capsys.readouterr().out


def test_check_does_not_require_docker_or_systemd(context, monkeypatch):
    import os
    import sys

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(
        shutil, "which", lambda _: pytest.fail("No executable prerequisite for read-only check")
    )
    HostEnvironment(context).environment()


@pytest.mark.parametrize("mode", ["native", "docker", "auto"])
def test_existing_plans_have_no_deployment_files_or_install_actions(mode, node, renderer):
    config = node.model_dump(mode="json")
    config["panel"]["installation"] = mode
    config["panel"]["port"] = 443  # Existing panels may legitimately use 443.
    node = Node.model_validate(config)
    assert renderer.artifacts(node) == {}
    assert renderer.plan(node, "check")["files"] == {}
    with pytest.raises(ValidationError, match="Existing installations"):
        renderer.plan(node, "fresh")


def test_report_persists_across_job_repository_reads(container, node, node_yaml):
    nodes = container.resolve(NodeRepository)
    revision = nodes.save(StoredNode.create(node, node_yaml)).revision
    jobs = container.resolve(JobRepository)
    job = Job.create(node.id, JobAction.CHECK)
    jobs.enqueue(job, revision)
    report = InstallationReport(observed_at="2026-10-30T10:00:00Z", capabilities={"docker": False})
    jobs.save_report(job.id, report)
    assert jobs.details(job.id).report == report
    assert ExecutionEvent(report=report).report == report


def test_existing_diagnostics_uses_published_port(context, tmp_path, monkeypatch):
    inventory = SystemInventory(context)
    monkeypatch.setattr(inventory, "service", lambda _: {})
    context.node["panel"]["installation"] = "docker"
    panels = PanelInspector(inventory)
    finding = panels.discover([docker_panel(tmp_path)])[0]
    inspector = InstallationInspector(context)
    inspector.panels = panels
    inspector.selected = finding
    assert ExistingDiagnostics(context, inspector)._endpoint(finding, "web") == ("127.0.0.1", 32053)


@pytest.mark.skipif(
    not shutil.which("openssl"), reason="openssl is needed for a real certificate fixture"
)
def test_real_certificate_dates_and_missing_private_file(context, tmp_path):
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-keyout",
            str(key),
            "-out",
            str(cert),
        ],
        check=True,
        capture_output=True,
    )
    inspector = CertificateInspector(SystemInventory(context))
    finding = inspector.inspect("panel", str(cert), str(key), Path)
    assert finding["state"] == "valid"
    assert finding["not_after"] and finding["sha256"]
    key.unlink()
    assert inspector.inspect("panel", str(cert), str(key), Path)["state"] == "missing"


def test_missing_native_database_is_never_created(context, tmp_path, monkeypatch):
    context.node["panel"].update(installation="native", database_path=str(tmp_path / "missing.db"))
    inventory = SystemInventory(context)
    monkeypatch.setattr(inventory, "service", lambda _: {"ActiveState": "active"})
    panels = PanelInspector(inventory)
    finding = panels.discover([])[0]
    assert finding["settings"] == {}
    assert not (tmp_path / "missing.db").exists()


def test_doctor_https_never_disables_verification(context, monkeypatch):
    import socket
    import ssl

    inspector = InstallationInspector(context)
    verifier = ExistingDiagnostics(context, inspector)

    class Connection:
        closed = False

        def close(self):
            self.closed = True

    connection = Connection()
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: connection)

    class TLS:
        def wrap_socket(self, stream, *, server_hostname):
            assert server_hostname == "panel.example.com"
            raise ssl.SSLCertVerificationError("untrusted")

    monkeypatch.setattr(ssl, "create_default_context", lambda: TLS())
    with pytest.raises(ssl.SSLCertVerificationError):
        verifier._socket(
            ("127.0.0.1", 8443), {"webCertFile": "/cert", "webDomain": "panel.example.com"}, "web"
        )
    assert connection.closed


def test_doctor_reaches_real_local_http_panel_with_discovered_path(context, tmp_path, monkeypatch):
    requests = []

    class Panel(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"panel fixture")

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Panel) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            inventory, _ = native_panel(
                context,
                tmp_path,
                monkeypatch,
                {
                    "webPort": str(server.server_port),
                    "webBasePath": "/existing-panel/",
                    "subEnable": "false",
                },
            )
            panels = PanelInspector(inventory)
            finding = panels.discover([])[0]
            inspector = InstallationInspector(context)
            inspector.panels, inspector.selected = panels, finding
            ExistingDiagnostics(context, inspector).check()
            assert requests == ["/existing-panel/"]
        finally:
            server.shutdown()
            thread.join(timeout=3)


@pytest.mark.skipif(sys.platform != "linux", reason="Actual remote execution requires Linux flock")
def test_runtime_backs_up_existing_native_panel_without_stopping_it(
    context, tmp_path, monkeypatch, capsys
):
    from app.agent.runtime import RemoteAgent

    source = create_database(tmp_path / "original.db")
    context.payload["action"] = "backup"
    context.node["panel"].update(installation="native", database_path=str(source))
    context.policy["lock_file"] = str(tmp_path / "nodekit.lock")
    original = source.read_bytes()
    monkeypatch.setattr(SystemInventory, "containers", lambda _: [])
    monkeypatch.setattr(
        SystemInventory,
        "service",
        lambda _, name: {"ActiveState": "active"} if name == "x-ui" else {},
    )
    monkeypatch.setattr(shutil, "which", lambda _: None)
    agent = RemoteAgent(context.payload)
    monkeypatch.setattr(agent.host, "environment", lambda: None)
    monkeypatch.setattr(
        agent.context, "command", lambda *a, **k: pytest.fail("Backup must not manage services")
    )
    agent.run()
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    snapshot = base64.b64decode(next(event["backup"] for event in events if "backup" in event))
    copy = tmp_path / "snapshot.db"
    copy.write_bytes(snapshot)
    with sqlite3.connect(copy) as db:
        assert db.execute("SELECT password FROM users").fetchone()[0] == "original-hash"
        assert (
            db.execute("SELECT stream_settings FROM inbounds").fetchone()[0]
            == "reality-private-key"
        )
    assert source.read_bytes() == original
    assert (
        next(event["report"] for event in events if "report" in event)["selected_panel"]
        == "native:x-ui"
    )


def test_remote_modules_import_without_unix_only_modules(monkeypatch):
    import builtins
    import importlib

    import app.agent.deployment as deployment
    import app.agent.runtime as runtime

    original = builtins.__import__

    def without_unix(name, *args, **kwargs):
        if name in {"pwd", "fcntl"}:
            raise ModuleNotFoundError(name)
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_unix)
    importlib.reload(runtime)
    importlib.reload(deployment)


def test_doctor_tls_trust_failure_is_warning_and_disabled_subscriptions_are_skipped(
    context, tmp_path, monkeypatch, capsys
):
    import ssl

    inventory, _ = native_panel(
        context,
        tmp_path,
        monkeypatch,
        {
            "webPort": "8443",
            "webBasePath": "/panel/",
            "webDomain": "panel.example.com",
            "webCertFile": "/example/cert",
            "subEnable": "false",
        },
    )
    panels = PanelInspector(inventory)
    finding = panels.discover([])[0]
    finding["certificates"] = []
    inspector = InstallationInspector(context)
    inspector.panels, inspector.selected = panels, finding

    def untrusted(*args):
        raise ssl.SSLCertVerificationError("certificate verify failed")

    monkeypatch.setattr(ExistingDiagnostics, "_socket", lambda self, *args: untrusted())
    assert ExistingDiagnostics(context, inspector).check() == []
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert any("Panel TLS:" in event["message"] and event["level"] == "warning" for event in events)
    assert any("disabled" in event["message"] for event in events)
    assert not any(
        "Subscription listener connection failed" in event["message"] for event in events
    )


def test_doctor_private_docker_listener_is_not_false_host_port_failure(
    context, tmp_path, monkeypatch, capsys
):
    inventory = SystemInventory(context)
    monkeypatch.setattr(inventory, "service", lambda _: {})
    context.node["panel"]["installation"] = "docker"
    container = docker_panel(tmp_path)
    container["NetworkSettings"]["Ports"] = {}
    container["NetworkSettings"]["Networks"] = {"proxy_net": {"IPAddress": ""}}
    panels = PanelInspector(inventory)
    finding = panels.discover([container])[0]
    inspector = InstallationInspector(context)
    inspector.panels, inspector.selected = panels, finding
    assert ExistingDiagnostics(context, inspector)._endpoint(finding, "web") is None
    assert ExistingDiagnostics(context, inspector).check() == []
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert any(event["level"] == "warning" for event in events)


def test_doctor_subscriptions_with_explicit_unreachable_port_are_reported(
    context, tmp_path, monkeypatch, capsys
):
    inventory, _ = native_panel(
        context,
        tmp_path,
        monkeypatch,
        {"webPort": "8443", "webBasePath": "/", "subEnable": "true", "subPort": "2097", "subListen": "127.0.0.1"},
    )
    panels = PanelInspector(inventory)
    finding = panels.discover([])[0]
    inspector = InstallationInspector(context)
    inspector.panels, inspector.selected = panels, finding
    monkeypatch.setattr(
        ExistingDiagnostics,
        "_socket",
        lambda self, *args: (_ for _ in ()).throw(ConnectionRefusedError("unavailable")),
    )
    failures = ExistingDiagnostics(context, inspector).check(raise_on_failure=False)
    assert any("Subscription listener connection failed" in msg for msg in failures)
    assert len(failures) >= 1
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert any(event["level"] == "error" and "Subscription" in event["message"] for event in events)

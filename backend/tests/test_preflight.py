"""Preflight is read-only and does not claim that a deployment can succeed."""

import json

from app.agent.context import AgentContext
from app.agent.preflight import PrerequisiteInspector
from app.entities import InstallationReport


def make_context(node, settings):
    return AgentContext(
        {
            "node": node.model_dump(mode="json"),
            "action": "check",
            "files": {},
            "runtime": {
                "deployment": settings.deployment.model_dump(mode="json"),
                "limits": settings.limits.model_dump(mode="json"),
            },
        }
    )


def test_six_profiles_require_only_tools_relevant_to_each_layout(node, settings, monkeypatch):
    context = make_context(node, settings)
    present = {"docker", "systemctl", "curl", "tar", "ssh", "openssl"}
    monkeypatch.setattr(
        "app.agent.preflight.shutil.which",
        lambda exe: f"/usr/bin/{exe}" if exe in present else None,
    )
    monkeypatch.setattr("app.agent.preflight.os.geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(context.runner, "status", lambda *args, **kwargs: 0)
    inspector = PrerequisiteInspector(context)
    capabilities = inspector.capabilities()
    assert capabilities["root"] and capabilities["docker_engine"] and capabilities["compose"]
    profiles = inspector.profiles(capabilities)
    assert len(profiles) == 6
    by_mode = {(item["panel_runtime"], item["caddy_runtime"]): item for item in profiles}
    assert by_mode["native", "none"]["ready"]
    assert by_mode["docker", "docker"]["ready"]
    assert "caddy" in by_mode["native", "native"]["missing"]
    assert "docker" not in by_mode["native", "none"]["required"]
    assert "systemctl" not in by_mode["docker", "docker"]["required"]


def test_docker_engine_unavailable_even_with_binary_present(node, settings, monkeypatch):
    context = make_context(node, settings)
    monkeypatch.setattr(
        "app.agent.preflight.shutil.which",
        lambda exe: "/usr/bin/docker" if exe == "docker" else None,
    )
    monkeypatch.setattr(context.runner, "status", lambda *args, **kwargs: 1)
    inspector = PrerequisiteInspector(context)
    status = inspector.capabilities()
    assert status["docker"] and not status["docker_engine"]
    assert not status["compose"]
    modes = inspector.profiles(status)
    assert all(
        "docker_engine" in item["missing"] for item in modes if item["panel_runtime"] == "docker"
    )


def test_optional_ssh_tunnels_affect_only_profiles_with_tunnels(node, settings):
    context = make_context(node, settings)
    inspector = PrerequisiteInspector(context)
    tools = {
        name: True
        for name in (
            "python3",
            "root",
            "docker",
            "docker_engine",
            "compose",
            "systemctl",
            "curl",
            "tar",
            "caddy",
            "ssh",
        )
    }
    assert inspector.profiles(tools)[4]["ready"]
    context.node["tunnels"] = [{"name": "gb"}]
    tools["ssh"] = False
    assert all("ssh" in item["missing"] for item in inspector.profiles(tools))


def test_old_and_new_reports_remain_compatible():
    report = InstallationReport(observed_at="2026-10-30T00:00:00Z")
    assert report.profiles == []
    data = report.model_dump(mode="json")
    data["profiles"] = [
        {
            "panel_runtime": "native",
            "caddy_runtime": "none",
            "required": ["root", "python3"],
            "missing": [],
            "ready": True,
        }
    ]
    assert len(InstallationReport.model_validate(json.loads(json.dumps(data))).profiles) == 1

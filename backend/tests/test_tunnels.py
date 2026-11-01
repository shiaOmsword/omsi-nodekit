import copy
import json
import os
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.agent.inbound_meta import public_inbound
from app.agent.tunnel_manager import TunnelManager, routed_template
from app.entities import Node
from app.entities.job_request import JobRequest
from tests.test_subscriptions import owned as owned


def template():
    return {
        "api": {"tag": "api"},
        "outbounds": [
            {"tag": "direct", "protocol": "freedom"},
            {"tag": "blocked", "protocol": "blackhole"},
            {
                "tag": "exit",
                "protocol": "vless",
                "settings": {
                    "vnext": [
                        {
                            "address": "203.0.113.12",
                            "port": 443,
                            "users": [{"id": "private-uuid", "flow": "xtls-rprx-vision"}],
                        }
                    ]
                },
                "streamSettings": {
                    "network": "tcp",
                    "security": "reality",
                    "realitySettings": {
                        "publicKey": "public-key",
                        "serverName": "example.com",
                        "shortId": "abcd",
                    },
                },
            },
        ],
        "routing": {
            "rules": [
                {"inboundTag": ["api-in"], "outboundTag": "api"},
                {"ip": ["geoip:private"], "outboundTag": "blocked"},
                {"inboundTag": ["in-xhttp"], "outboundTag": "direct"},
            ]
        },
    }


def test_scoped_route_preserves_credentials_default_api_denies_and_is_idempotent():
    original = template()
    before = copy.deepcopy(original)
    result, outbound, rule = routed_template(
        original, "exit", {"local_port": 15443}, "ssh-msk-gb", "in-xhttp"
    )
    assert original == before
    assert result["outbounds"][:-1] == original["outbounds"]
    assert result["routing"]["rules"][:2] == original["routing"]["rules"][:2]
    assert result["routing"]["rules"][2] == rule
    assert result["routing"]["rules"][3:] == original["routing"]["rules"][2:]
    assert outbound["streamSettings"] == original["outbounds"][-1]["streamSettings"]
    assert (
        outbound["settings"]["vnext"][0]["users"]
        == original["outbounds"][-1]["settings"]["vnext"][0]["users"]
    )
    assert outbound["settings"]["vnext"][0]["address"] == "127.0.0.1"
    assert outbound["settings"]["vnext"][0]["port"] == 15443
    previous = {"outbound": outbound, "rule": rule}
    again, _, _ = routed_template(
        result, "exit", {"local_port": 15443}, "ssh-msk-gb", "in-xhttp", previous
    )
    assert again == result
    for inbound, state in [("in-xhttp", None), ("another-in", previous)]:
        with pytest.raises(ValueError):
            routed_template(result, "exit", {"local_port": 15443}, "ssh-msk-gb", inbound, state)


@pytest.mark.parametrize("change", ["multiple", "proxy", "dialer", "transport", "security", "bind"])
def test_unsupported_or_chained_outbounds_rejected(change):
    config = template()
    source = config["outbounds"][-1]
    if change == "multiple":
        source["settings"]["vnext"].append(copy.deepcopy(source["settings"]["vnext"][0]))
    elif change == "proxy":
        source["proxySettings"] = {"tag": "another"}
    elif change == "dialer":
        source["streamSettings"]["sockopt"] = {"dialerProxy": "another"}
    elif change == "transport":
        source["streamSettings"]["network"] = "xhttp"
    elif change == "bind":
        source["sendThrough"] = "203.0.113.10"
    else:
        source["streamSettings"]["security"] = "tls"
    with pytest.raises(ValueError):
        routed_template(config, "exit", {"local_port": 15443}, "ssh-msk-gb", "in-xhttp")


@pytest.mark.parametrize(
    "outer_string,inner_string", [(False, True), (True, False), (False, False)]
)
def test_template_handles_documented_and_actual_3110_api_shapes(outer_string, inner_string):
    obj = {"xraySetting": json.dumps(template()) if inner_string else template()}
    api = SimpleNamespace(request=lambda *a: json.dumps(obj) if outer_string else obj)
    assert TunnelManager.template(api) == template()


@pytest.fixture
def operation(owned, monkeypatch):
    context = owned.context
    context.node["tunnels"] = [
        {
            "name": "gb",
            "host": "203.0.113.12",
            "user": "omsi",
            "ssh_port": 2222,
            "local_port": 15443,
            "target_port": 8443,
            "identity_file": "/home/omsi/.ssh/gb",
            "known_hosts_file": "/home/omsi/.ssh/known_hosts",
        }
    ]
    units = owned.base / "units"
    units.mkdir()
    context.policy.update(unit_directory=str(units), readiness_attempts=1)
    unit = context.unit("gb")
    context.payload["files"][unit] = "[Unit]\nDescription=owned fixture\n"
    item = {
        "id": 1,
        "remark": "phone",
        "tag": "in-xhttp",
        "enable": True,
        "port": 10080,
        "listen": "172.30.50.1",
        "protocol": "vless",
        "settings": {},
        "streamSettings": {"network": "xhttp", "security": "none"},
    }
    context.payload["options"] = {
        "tunnel": {
            "name": "gb",
            "outbound_tag": "exit",
            "id": 1,
            "expected_fingerprint": public_inbound(item)["fingerprint"],
        }
    }
    state = SimpleNamespace(
        item=item, config=template(), calls=[], fail=False, enabled=False, active=False
    )

    def request(path, data=None, **kwargs):
        state.calls.append(path)
        if path.startswith("inbounds/get/"):
            return copy.deepcopy(item)
        if path == "xray/":
            return {"xraySetting": json.dumps(state.config)}
        if path == "xray/update":
            assert kwargs == {"form": True}
            state.config = json.loads(data["xraySetting"])
        if path == "server/restartXrayService" and state.fail:
            state.fail = False
            raise ValueError("private-sensitive-body")

    monkeypatch.setattr(
        "app.agent.tunnel_manager.managed_api", lambda *a: SimpleNamespace(request=request)
    )

    def command(args, **kwargs):
        owned.calls.append(args)
        if args[:2] == ["systemctl", "enable"]:
            state.enabled = state.active = True
        if args[:2] == ["systemctl", "stop"]:
            state.active = False
        if args[:2] == ["systemctl", "disable"]:
            state.enabled = False
        return ""

    monkeypatch.setattr(context, "command", command)
    monkeypatch.setattr(
        context,
        "status",
        lambda a: 0 if (state.active if "is-active" in a else state.enabled) else 1,
    )
    manager = TunnelManager(
        context,
        SimpleNamespace(require_endpoint=lambda *a: None, port_open=lambda *a: True),
        owned.operation.database,
        owned.inspector,
    )
    monkeypatch.setattr(manager, "probe", lambda *a: None)
    monkeypatch.setattr(manager, "runtime_matches", lambda *a: True)
    return SimpleNamespace(manager=manager, owned=owned, state=state, unit=units / unit)


def test_apply_idempotent_and_private_state(operation, capsys):
    operation.manager.apply(operation.owned.base)
    operation.manager.apply(operation.owned.base)
    assert operation.state.enabled and operation.state.active
    assert len(operation.state.config["outbounds"]) == 4
    if os.name != "nt":
        assert (operation.owned.base / "tunnel-gb.json").stat().st_mode & 0o777 == 0o600
    assert "private-uuid" not in capsys.readouterr().out
    assert list(operation.owned.base.glob("before-tunnel-*.db"))


def test_restart_failure_rolls_back_template_and_service(operation, capsys):
    original = copy.deepcopy(operation.state.config)
    operation.state.fail = True
    with pytest.raises(RuntimeError, match="routing API update") as error:
        operation.manager.apply(operation.owned.base)
    assert "private-sensitive-body" not in str(error.value)
    assert "private-sensitive-body" not in capsys.readouterr().out
    assert operation.state.config == original
    assert not operation.unit.exists()
    assert not operation.state.active and not operation.state.enabled


def test_probe_failure_never_changes_routes(operation, monkeypatch):
    monkeypatch.setattr(operation.manager, "probe", lambda *a: (_ for _ in ()).throw(ValueError()))
    with pytest.raises(RuntimeError, match="HTTPS through"):
        operation.manager.apply(operation.owned.base)
    assert "xray/update" not in operation.state.calls
    assert not operation.unit.exists()


def test_operator_edit_during_failure_is_preserved_with_running_forward(
    operation, monkeypatch, capsys
):
    count = 0

    def probe(*args):
        nonlocal count
        count += 1
        if count == 2:
            operation.state.config["operator"] = True
            raise ValueError()

    monkeypatch.setattr(operation.manager, "probe", probe)
    with pytest.raises(RuntimeError):
        operation.manager.apply(operation.owned.base)
    assert operation.state.config["operator"] is True
    assert operation.unit.exists() and operation.state.active
    assert "rollback" in capsys.readouterr().out.lower()


@pytest.mark.parametrize("changed", ["unit", "fingerprint", "key"])
def test_rejected_preflight_never_stops_or_overwrites_a_service(operation, monkeypatch, changed):
    if changed == "unit":
        operation.unit.write_text("operator service")
    elif changed == "fingerprint":
        operation.owned.context.payload["options"]["tunnel"]["expected_fingerprint"] = "0" * 64
    else:
        monkeypatch.setattr(
            operation.owned.context, "command", lambda *a, **k: (_ for _ in ()).throw(ValueError())
        )
    with pytest.raises(RuntimeError):
        operation.manager.apply(operation.owned.base)
    if changed == "unit":
        assert operation.unit.read_text() == "operator service"
    assert not any("stop" in a or "disable" in a for a in operation.owned.calls)
    assert "xray/update" not in operation.state.calls


def test_arguments_and_systemd_unit(node, renderer):
    request = {"name": "gb", "id": 1, "expected_fingerprint": "a" * 64, "outbound_tag": "exit"}
    assert JobRequest(action="tunnel", revision="b" * 64, tunnel=request).action == "tunnel"
    with pytest.raises(ValidationError):
        JobRequest(action="check", revision="b" * 64, tunnel=request)
    with pytest.raises(ValidationError):
        JobRequest(action="tunnel", revision="b" * 64)
    data = node.model_dump()
    data["tunnels"] = [{"name": "gb", "host": "203.0.113.12", "ssh_port": 2222}]
    unit = renderer.tunnel_unit(Node.model_validate(data), 0)
    assert "-F none -N -T -p 2222" in unit
    assert "-L 127.0.0.1:15443:127.0.0.1:443" in unit
    assert "StrictHostKeyChecking=yes" in unit and "ExitOnForwardFailure=yes" in unit
    assert "Restart=always" in unit and "ServerAliveInterval=" in unit
    data["tunnels"][0]["name"] = "panel"
    with pytest.raises(ValidationError):
        Node.model_validate(data)


@pytest.mark.parametrize("response_bytes", [0, 1024])
def test_probe_requires_return_body_and_cleans_private_process_files(
    operation, monkeypatch, response_bytes
):
    binary = operation.owned.base / "fixture-xray"
    binary.touch()
    monkeypatch.setattr("app.agent.tunnel_manager.runtime_paths", lambda *a: (None, binary))
    calls = []

    class Process:
        def __init__(self, args, **kwargs):
            self.path = args[-1]
            self.stopped = False
            calls.append(self)

        def poll(self):
            return 0 if self.stopped else None

        def terminate(self):
            self.stopped = True

        def wait(self, timeout):
            return 0

    monkeypatch.setattr("app.agent.tunnel_manager.subprocess.Popen", Process)
    monkeypatch.setattr(
        "app.agent.tunnel_manager.curl_probe",
        lambda *a, **kw: {"ok": True, "bytes": response_bytes},
    )
    if response_bytes:
        assert (
            TunnelManager.probe(operation.manager, template()["outbounds"][-1])["bytes"]
            == response_bytes
        )
    else:
        with pytest.raises(ValueError):
            TunnelManager.probe(operation.manager, template()["outbounds"][-1])
    from pathlib import Path

    assert calls[0].stopped and not Path(calls[0].path).exists()


def test_reapply_preserves_default_and_operator_route_priority():
    result, outbound, rule = routed_template(
        template(), "exit", {"local_port": 15443}, "ssh-msk-gb", "in-xhttp"
    )
    result["outbounds"].remove(outbound)
    result["outbounds"].insert(0, outbound)
    result["routing"]["rules"].insert(0, {"domain": ["example.org"], "outboundTag": "direct"})
    again, _, _ = routed_template(
        result,
        "exit",
        {"local_port": 15443},
        "ssh-msk-gb",
        "in-xhttp",
        {"outbound": outbound, "rule": rule},
    )
    assert again == result


def test_forward_rechecks_unit_after_preflight_before_enabling(operation):
    from app.agent.tunnel_forward import TunnelForward

    context = operation.owned.context
    forward = TunnelForward(context, operation.manager.host, context.node["tunnels"][0])
    forward.preflight()
    operation.unit.write_text("operator service")
    with pytest.raises(ValueError):
        forward.start()
    forward.rollback()
    assert operation.unit.read_text() == "operator service"
    assert not any("enable" in call for call in operation.owned.calls)


def test_applied_tunnel_does_not_block_later_subscription_configuration(operation):
    operation.manager.apply(operation.owned.base)
    manifest = json.loads((operation.owned.base / "manifest.json").read_text())
    assert manifest["node"]["tunnels"] == operation.owned.context.node["tunnels"]
    operation.owned.operation.apply(operation.owned.base)


def test_metadata_write_failure_rolls_back_route_service_and_ownership(operation, monkeypatch):
    from app.agent import tunnel_manager

    write = tunnel_manager.private_write
    before = operation.state.config
    manifest_path = operation.owned.base / "manifest.json"
    original_manifest = manifest_path.read_bytes()

    def fail_manifest(path, data):
        if path == manifest_path:
            raise OSError()
        write(path, data)

    monkeypatch.setattr(tunnel_manager, "private_write", fail_manifest)
    with pytest.raises(RuntimeError):
        operation.manager.apply(operation.owned.base)
    assert operation.state.config == before
    assert not operation.unit.exists()
    assert not (operation.owned.base / "tunnel-gb.json").exists()
    assert manifest_path.read_bytes() == original_manifest


def test_reapply_tracks_the_same_inbound_after_3xui_migrates_its_tag(operation):
    operation.manager.apply(operation.owned.base)
    old_tag = operation.state.item["tag"]
    operation.state.item.update(tag="in-10443-tcp", port=10443)
    for rule in operation.state.config["routing"]["rules"]:
        if old_tag in rule.get("inboundTag", []):
            rule["inboundTag"] = [
                "in-10443-tcp" if tag == old_tag else tag for tag in rule["inboundTag"]
            ]
    request = operation.owned.context.payload["options"]["tunnel"]
    request["expected_fingerprint"] = public_inbound(operation.state.item)["fingerprint"]
    operation.manager.apply(operation.owned.base)
    state = json.loads((operation.owned.base / "tunnel-gb.json").read_text())
    assert state["inbound_id"] == 1
    assert state["rule"]["inboundTag"] == ["in-10443-tcp"]
    assert state["rule"] in operation.state.config["routing"]["rules"]


@pytest.mark.parametrize("network", ["tcp", "raw"])
def test_flat_vless_preserves_every_field_and_supports_idempotent_routing(network):
    config = template()
    source = config["outbounds"][-1]
    source["settings"] = {
        "address": "203.0.113.12",
        "port": 11474,
        "id": "private-uuid",
        "encryption": "none",
        "flow": "xtls-rprx-vision",
        "testseed": [900, 500, 900, 256],
    }
    source["streamSettings"]["network"] = network
    before = copy.deepcopy(config)
    result, outbound, rule = routed_template(
        config, "exit", {"local_port": 15443}, "ssh-msk-nd", "in-xhttp"
    )
    assert config == before
    assert result["outbounds"][:-1] == before["outbounds"]
    expected = copy.deepcopy(source)
    expected["tag"] = "ssh-msk-nd"
    expected["settings"].update(address="127.0.0.1", port=15443)
    assert outbound == expected
    again, _, _ = routed_template(
        result,
        "exit",
        {"local_port": 15443},
        "ssh-msk-nd",
        "in-xhttp",
        {"outbound": outbound, "rule": rule},
    )
    assert again == result


@pytest.mark.parametrize(
    "settings",
    [
        {"address": "exit.example", "port": 443},
        {"address": "exit.example", "port": 0, "id": "private-uuid"},
        {"address": "exit.example", "port": True, "id": "private-uuid"},
        {"vnext": [{"address": "exit.example", "port": 443, "users": []}]},
        {"vnext": [], "address": "exit.example", "port": 443, "id": "private-uuid"},
    ],
)
def test_incomplete_or_mixed_vless_schemas_fail_before_mutation(settings):
    config = template()
    config["outbounds"][-1]["settings"] = settings
    before = copy.deepcopy(config)
    with pytest.raises(ValueError):
        routed_template(config, "exit", {"local_port": 15443}, "ssh-msk-nd", "in-xhttp")
    assert config == before

import copy
import json
import os
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient

from app.agent.caddy_ports import CaddyPortsTransaction
from app.agent.egress import curl_probe, routing_inventory
from app.agent.firewall import (
    FirewallTransaction,
    desired_rules,
    inspect_firewall,
    network_checks,
    parse_status,
    permitted,
    public_firewall,
    rule_spec,
)
from app.agent.inbound_manager import InboundManager, identities, matches_update
from app.agent.inbound_meta import public_inbound
from app.agent.traffic_probe import TrafficProbe
from app.container import build_container
from app.create_app import create_app
from app.entities import ExecutionEvent
from app.ports import NodeExecutor
from framework.tasks import TaskScheduler
from tests.test_subscriptions import owned as owned


def finding(lines="", state="active"):
    return {**parse_status(f"Status: {state}\n{lines}"), "state": state, "default_incoming": "deny"}


def test_ufw_order_scope_ipv6_and_private_comments():
    fw = finding("""[ 1] 8443/tcp DENY IN Anywhere
[ 2] 8443/tcp ALLOW IN Anywhere
[ 3] 172.30.50.1 2097/tcp on br-example ALLOW IN 172.30.50.0/24 # private-comment
[ 4] 2096/tcp (v6) ALLOW IN Anywhere (v6)
[ 5] 10000:10100/tcp ALLOW IN 203.0.113.0/24
""")
    assert permitted(fw, rule_spec(8443)) is False
    assert permitted(fw, rule_spec(2096)) is False
    scoped = rule_spec(
        2097, source="172.30.50.0/24", destination="172.30.50.1", interface="br-example"
    )
    assert permitted(fw, scoped) is True
    assert permitted(fw, rule_spec(2097)) is False
    assert permitted(fw, rule_spec(10001, source="203.0.113.5")) is True
    assert "private-comment" not in json.dumps(public_firewall(fw))


@pytest.mark.parametrize("failure", [False, True])
def test_firewall_inspection_reads_english_policy_or_reports_unknown(owned, monkeypatch, failure):
    calls = []
    monkeypatch.setattr("app.agent.firewall.shutil.which", lambda name: "/fixture/ufw")

    def completed(args, **kwargs):
        calls.append(args)
        output = (
            "Status: active\n[ 1] 8443/tcp ALLOW IN Anywhere"
            if args[-1] == "numbered"
            else "Default: deny (incoming), allow (outgoing), deny (routed)"
        )
        return SimpleNamespace(returncode=1 if failure else 0, stdout=output)

    monkeypatch.setattr(owned.context.runner, "completed", completed)
    actual = inspect_firewall(owned.context)
    assert all(c[:3] == ["env", "LC_ALL=C", "ufw"] for c in calls)
    if failure:
        assert actual["state"] == "unknown" and actual["warnings"]
    else:
        assert actual["state"] == "active" and actual["default_outgoing"] == "allow"


class UFW:
    def __init__(self, monkeypatch, context, initial=None):
        self.state = initial or finding()
        self.calls = []
        monkeypatch.setattr(
            "app.agent.firewall.inspect_firewall", lambda c: copy.deepcopy(self.state)
        )
        monkeypatch.setattr(context.runner, "run", self.run)

    def run(self, args, **kwargs):
        self.calls.append(args)
        args = args[4:]
        delete = "delete" in args
        if "comment" in args and "from" in args:
            comment = args[args.index("comment") + 1]
            if delete:
                self.state["rules"] = [
                    r for r in self.state["rules"] if r.get("comment") != comment
                ]
            else:
                interface = " on " + args[args.index("on") + 1] if "on" in args else ""
                destination = args[args.index("to") + 1]
                destination = "" if destination == "any" else destination + " "
                source = args[args.index("from") + 1]
                source = "Anywhere" if source == "any" else source
                line = f"[ 1] {destination}{args[args.index('port') + 1]}/{args[args.index('proto') + 1]}{interface} ALLOW IN {source} # {comment}"
                added = finding(line)["rules"]
                self.state["rules"] = (
                    added + self.state["rules"] if "insert" in args else self.state["rules"] + added
                )
        elif delete:
            port = args[-1].split("/")[0]
            self.state["rules"] = [
                r for r in self.state["rules"] if not (r["port"] == port and not r["managed"])
            ]
        return ""


def test_firewall_transaction_reconciles_old_and_new_and_rolls_back_ledger(owned, monkeypatch):
    ufw = UFW(monkeypatch, owned.context)
    host = SimpleNamespace(port_open=lambda p: False)
    first = FirewallTransaction(owned.context, owned.base)
    first.ensure([rule_spec(8443)])
    first.commit()
    before = (owned.base / "firewall-rules.json").read_bytes()
    second = FirewallTransaction(owned.context, owned.base)
    second.ensure([rule_spec(9443)])
    second.prune({9443}, host)
    second.commit()
    assert {r["port"] for r in ufw.state["rules"]} == {"9443"}
    second.rollback()
    assert {r["port"] for r in ufw.state["rules"]} == {"8443"}
    assert (owned.base / "firewall-rules.json").read_bytes() == before
    assert not any("enable" in call or "reset" in call for call in ufw.calls)


def test_newly_added_then_deleted_inbound_does_not_leave_a_firewall_hole(owned, monkeypatch):
    ufw = UFW(monkeypatch, owned.context)
    tx = FirewallTransaction(owned.context, owned.base)
    tx.ensure([rule_spec(8443)])
    tx.prune(set(), SimpleNamespace(port_open=lambda p: False))
    tx.commit()
    assert not ufw.state["rules"]
    tx.rollback()
    assert not ufw.state["rules"]


def test_explicit_firewall_deny_is_not_bypassed(owned, monkeypatch):
    ufw = UFW(monkeypatch, owned.context, finding("[ 1] 8443/tcp DENY IN Anywhere"))
    tx = FirewallTransaction(owned.context, owned.base)
    with pytest.raises(RuntimeError):
        tx.ensure([rule_spec(8443)])
    assert not ufw.calls
    tx.rollback()
    assert len(ufw.state["rules"]) == 1 and ufw.state["rules"][0]["action"] == "DENY"


def test_manual_rules_and_other_service_ports_are_preserved(owned, monkeypatch):
    ufw = UFW(
        monkeypatch,
        owned.context,
        finding("[ 1] 8443/tcp ALLOW IN Anywhere\n[ 2] 22/tcp ALLOW IN Anywhere"),
    )
    tx = FirewallTransaction(owned.context, owned.base)
    tx.ensure([rule_spec(8443)])
    tx.prune(set(), SimpleNamespace(port_open=lambda p: False))
    assert not ufw.calls
    tx.close_manual(8443, {22}, SimpleNamespace(port_open=lambda p: False))
    assert [r["port"] for r in ufw.state["rules"]] == ["22"]
    assert ufw.calls[-1][-3:] == ["delete", "allow", "8443/tcp"]


@pytest.mark.parametrize("state", ["inactive", "unavailable"])
def test_firewall_never_enables_an_inactive_firewall(owned, monkeypatch, state):
    ufw = UFW(monkeypatch, owned.context, finding(state=state))
    FirewallTransaction(owned.context, owned.base).ensure([rule_spec(8443)])
    assert not ufw.calls


def test_private_backend_rule_is_scoped_to_discovered_caddy_bridge(owned, monkeypatch):
    monkeypatch.setattr(owned.context, "directory", lambda: owned.base)
    owned.context.node["deployment"].update(
        caddy_id="docker:shared-caddy", subscription_bind="172.30.50.1"
    )
    report = {
        "firewall": finding(),
        "caddy": [
            {
                "id": "docker:abc",
                "container": "shared-caddy",
                "installation": "docker",
                "network_mode": "bridge",
                "published_ports": ["0.0.0.0:443->443/tcp"],
                "bridge_networks": [
                    {
                        "gateway": "172.30.50.1",
                        "subnet": "172.30.50.0/24",
                        "interface": "br-example",
                    }
                ],
            }
        ],
    }
    specs = desired_rules(owned.context, report)
    private = next(r for r in specs if r["scope"] == "subscription")
    assert private == rule_spec(
        2097,
        source="172.30.50.0/24",
        destination="172.30.50.1",
        interface="br-example",
        scope="subscription",
    )
    assert not any(r["port"] == 2097 and r["source"] == "any" for r in specs)
    assert any(
        c["name"] == "caddy_port" and "2096" in c["detail"] and c["state"] == "warning"
        for c in network_checks(owned.context, report)
    )


@pytest.fixture
def compose(owned, monkeypatch):
    folder = owned.base / "infra"
    folder.mkdir()
    source = folder / "compose.yaml"
    config = {
        "services": {
            "caddy": {
                "image": "caddy:2",
                "environment": {"TOKEN": "private-token"},
                "ports": [{"target": 443, "published": "443", "protocol": "tcp"}],
            },
            "other": {"image": "other:1"},
        }
    }
    source.write_text(json.dumps(config))
    container = {
        "Id": "abc",
        "Config": {"Image": "caddy:2", "Labels": {"com.docker.compose.config-hash": "a" * 64}},
    }
    proxy = {
        "id": "docker:abc",
        "container": "shared-caddy",
        "installation": "docker",
        "network_mode": "bridge",
        "compose_project": "infra",
        "compose_service": "caddy",
        "compose_working_dir": str(folder),
        "compose_files": [str(source)],
        "published_ports": ["0.0.0.0:443->443/tcp"],
    }
    owned.context.node["deployment"]["caddy_id"] = "docker:shared-caddy"
    inspector = SimpleNamespace(
        report={"caddy": [proxy]}, inventory=SimpleNamespace(containers=lambda: [container])
    )
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        assert kwargs.get("sensitive")
        if args[:2] == ["docker", "inspect"]:
            return json.dumps([container])
        if "--hash" in args:
            return "caddy " + "a" * 64
        if "config" in args:
            merged = copy.deepcopy(config)
            output = folder / "compose.nodekit-test-node.ports.yaml"
            if str(output) in args and output.exists():
                merged["services"]["caddy"]["ports"] += json.loads(output.read_text())["services"][
                    "caddy"
                ]["ports"]
            return json.dumps(merged)
        if "up" in args:
            container["Id"] = "new-container"
        return ""

    monkeypatch.setattr(owned.context.runner, "run", run)
    monkeypatch.setattr(
        owned.context.runner, "completed", lambda *a, **k: SimpleNamespace(returncode=0)
    )
    monkeypatch.setattr(
        "app.agent.caddy_ports.socket.socket",
        lambda *a: nullcontext(SimpleNamespace(bind=lambda *a: None)),
    )
    return SimpleNamespace(
        tx=CaddyPortsTransaction(owned.context, inspector),
        source=source,
        config=config,
        container=container,
        calls=calls,
        folder=folder,
    )


def test_compose_only_adds_missing_ports_and_recreates_caddy(compose):
    original = compose.source.read_bytes()
    compose.tx.prepare()
    assert compose.tx.missing == [80, 2096]
    assert compose.tx.apply()
    output = compose.tx.output
    document = json.loads(output.read_text())
    assert set(document["services"]["caddy"]) == {"ports"}
    assert [p["target"] for p in document["services"]["caddy"]["ports"]] == [80, 2096]
    assert compose.source.read_bytes() == original
    ups = [c for c in compose.calls if "up" in c]
    assert len(ups) == 1 and ups[0][-1] == "caddy" and "--no-deps" in ups[0]
    assert "private-token" not in output.read_text()
    compose.tx.rollback()
    assert not output.exists() and compose.source.read_bytes() == original


@pytest.mark.parametrize("drift", ["file", "container", "override"])
def test_compose_drift_is_rejected_before_writing_or_restarting(compose, drift):
    compose.tx.prepare()
    if drift == "file":
        compose.source.write_text("changed by operator")
    elif drift == "container":
        compose.container["Id"] = "someone-elses-container"
    else:
        compose.tx.output.write_text("operator override")
    with pytest.raises(RuntimeError):
        compose.tx.apply()
    assert (
        not compose.tx.output.exists()
        if drift != "override"
        else compose.tx.output.read_text() == "operator override"
    )
    assert not any("up" in c for c in compose.calls)


def test_compose_rollback_does_not_overwrite_an_operator_edit(compose):
    compose.tx.prepare()
    compose.tx.apply()
    compose.tx.output.write_text("operator override")
    with pytest.raises(RuntimeError):
        compose.tx.rollback()
    assert compose.tx.output.read_text() == "operator override"


@pytest.fixture
def managed(owned, monkeypatch):
    item = {
        "id": 1,
        "remark": "nodekit:test-node:first",
        "enable": True,
        "port": 8443,
        "listen": "0.0.0.0",
        "protocol": "vless",
        "tag": "in-8443-tcp",
        "settings": {
            "clients": [
                {
                    "id": "00000000-0000-4000-8000-000000000001",
                    "subId": "private-sub",
                    "email": "client",
                    "enable": True,
                }
            ]
        },
        "streamSettings": {
            "network": "tcp",
            "security": "reality",
            "realitySettings": {
                "privateKey": "private-key",
                "shortIds": ["aabbccdd"],
                "serverNames": ["example.com"],
                "target": "example.com:443",
                "settings": {"publicKey": "a" * 43},
            },
        },
    }
    items = {1: item}

    def request(path, data=None):
        operation = path.split("/")[1]
        if operation == "list":
            return copy.deepcopy(list(items.values()))
        key = int(path.rsplit("/", 1)[1])
        if operation == "get":
            return copy.deepcopy(items[key])
        if operation == "del":
            del items[key]
        elif operation == "update":
            saved = copy.deepcopy(data)
            old = items[key]
            if (
                saved["port"] != old["port"]
                and old["tag"] == f"in-{old['port']}-tcp"
                and saved["tag"] == old["tag"]
            ):
                saved["tag"] = f"in-{saved['port']}-tcp"
            items[key] = saved

    monkeypatch.setattr(
        "app.agent.inbound_manager.managed_api", lambda *a: SimpleNamespace(request=request)
    )
    monkeypatch.setattr(
        "app.agent.firewall.inspect_firewall", lambda c: finding(state="unavailable")
    )
    monkeypatch.setattr(owned.context, "directory", lambda: owned.base)
    owned.context.payload["options"] = {
        "inbound": {
            "id": 1,
            "operation": "update",
            "port": 9443,
            "remark": "Renamed",
            "server_name": "new.example.com",
            "expected_fingerprint": public_inbound(item)["fingerprint"],
        }
    }
    owned.manager = InboundManager(
        owned.context, owned.operation.host, owned.operation.database, owned.inspector
    )
    monkeypatch.setattr(owned.operation.host, "port_open", lambda p, *a: p != 8443)
    owned.items = items
    return owned


def test_inbound_edit_preserves_clients_keys_and_tracks_automatic_tag(managed, capsys):
    before = identities(managed.items[1])
    managed.manager.apply(managed.base)
    item = managed.items[1]
    assert (item["port"], item["remark"], item["tag"]) == (9443, "Renamed", "in-9443-tcp")
    assert item["streamSettings"]["realitySettings"]["target"] == "new.example.com:443"
    assert identities(item) == before
    assert json.loads((managed.base / "inbound-identities.json").read_text())["first"]["edited"]
    assert "private-" not in capsys.readouterr().out


def test_inbound_rollback_recognizes_regenerated_tag(managed, monkeypatch):
    original = copy.deepcopy(managed.items[1])
    monkeypatch.setattr(
        managed.manager,
        "_remember",
        lambda *a: (_ for _ in ()).throw(RuntimeError("fixture failure")),
    )
    with pytest.raises(RuntimeError, match="fixture failure"):
        managed.manager.apply(managed.base)
    assert managed.items[1] == original
    assert not (managed.base / "inbound-identities.json").exists()


def test_inbound_stale_and_reserved_port_are_rejected_before_mutation(managed):
    original = copy.deepcopy(managed.items[1])
    managed.context.payload["options"]["inbound"]["expected_fingerprint"] = "0" * 64
    with pytest.raises(RuntimeError):
        managed.manager.apply(managed.base)
    assert managed.items[1] == original and not list(managed.base.glob("before-inbound-*.db"))
    managed.context.payload["options"]["inbound"].update(
        expected_fingerprint=public_inbound(original)["fingerprint"], port=2053
    )
    with pytest.raises(RuntimeError):
        managed.manager.apply(managed.base)
    assert managed.items[1] == original


def test_delete_persists_tombstone_and_removes_exported_links(managed):
    managed.context.payload["options"]["inbound"] = {
        "id": 1,
        "operation": "delete",
        "expected_fingerprint": public_inbound(managed.items[1])["fingerprint"],
    }
    (managed.base / "subscriptions.json").write_text(
        json.dumps([{"name": "first", "url": "private-url"}])
    )
    managed.manager.apply(managed.base)
    assert not managed.items
    assert json.loads((managed.base / "inbound-identities.json").read_text())["first"]["deleted"]
    assert json.loads((managed.base / "subscriptions.json").read_text()) == []


def test_update_does_not_accept_arbitrary_tag_changes(managed):
    old = copy.deepcopy(managed.items[1])
    proposed = {**old, "port": 9443}
    assert matches_update({**proposed, "tag": "in-9443-tcp"}, proposed, old)
    assert not matches_update({**proposed, "tag": "unrelated"}, proposed, old)
    old["tag"] = "custom"
    assert not matches_update({**proposed, "tag": "in-9443-tcp"}, {**old, "port": 9443}, old)


def test_routing_inventory_reports_protocol_and_missing_reference_without_credentials(
    managed, monkeypatch
):
    config = managed.base / "runtime-config.json"
    config.write_text(
        json.dumps(
            {
                "outbounds": [
                    {
                        "tag": "From_MSK",
                        "protocol": "vless",
                        "settings": {"password": "private-password"},
                        "streamSettings": {"sockopt": {"dialerProxy": "missing"}},
                    }
                ],
                "routing": {"rules": [{"inboundTag": ["in-8443-tcp"], "outboundTag": "missing"}]},
            }
        )
    )
    monkeypatch.setattr("app.agent.egress.runtime_paths", lambda *a: (config, None))
    result = routing_inventory(managed.context, managed.inspector)
    assert result["outbounds"][0]["protocol"] == "vless" and result["warnings"]
    assert "private-password" not in json.dumps(result)


def test_curl_probe_reports_actual_http_bytes_and_disables_environment_proxy(owned, monkeypatch):
    calls = []

    def completed(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="200|0.25|123", stderr="")

    monkeypatch.setattr(owned.context.runner, "completed", completed)
    assert curl_probe(owned.context, "https://example.com")["bytes"] == 123
    curl_probe(owned.context, "https://example.com", socks_port=11111)
    assert calls[0][calls[0].index("--proxy") + 1] == ""
    assert calls[1][calls[1].index("--proxy") + 1] == "socks5h://127.0.0.1:11111"


@pytest.mark.parametrize(
    "api_tag,routed_tag,missing",
    [
        ("api", "api", False),
        ("admin-api", "admin-api", False),
        ("api", "typo-api", True),
        (None, "api", True),
    ],
)
def test_routing_inventory_recognizes_only_the_configured_api_outbound(
    managed, monkeypatch, api_tag, routed_tag, missing
):
    config = {
        "outbounds": [{"tag": "direct", "protocol": "freedom"}],
        "routing": {"rules": [{"inboundTag": ["api-in"], "outboundTag": routed_tag}]},
    }
    if api_tag:
        config["api"] = {"tag": api_tag, "services": ["HandlerService"]}
    path = managed.base / "api-runtime.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr("app.agent.egress.runtime_paths", lambda *a: (path, None))
    result = routing_inventory(managed.context, managed.inspector)
    assert result["readable"]
    assert bool(result["warnings"]) is missing
    assert result["outbounds"] == [{"tag": "direct", "protocol": "freedom", "via": None}]
    assert result["default_tag"] == "direct"


@pytest.mark.parametrize("fail", [False, True])
def test_traffic_probe_uses_private_temporary_client_and_always_cleans_up(
    managed, monkeypatch, fail
):
    binary = managed.base / "xray"
    binary.touch()
    monkeypatch.setattr("app.agent.traffic_probe.runtime_paths", lambda *a: (None, binary))
    managed.context.payload["options"] = {
        "traffic": {
            "id": 1,
            "expected_fingerprint": public_inbound(managed.items[1])["fingerprint"],
        }
    }
    paths, stopped = [], []

    def process(args, **kwargs):
        from pathlib import Path

        path = Path(args[-1])
        assert "private-client" in path.read_text()
        if os.name != "nt":
            assert path.stat().st_mode & 0o777 == 0o600
        paths.append(path)
        return SimpleNamespace(
            poll=lambda: None, terminate=lambda: stopped.append(True), wait=lambda **k: None
        )

    monkeypatch.setattr("app.agent.traffic_probe.subprocess.Popen", process)

    def probe(*a, **k):
        if fail:
            raise RuntimeError("fixture failure")
        return {"ok": True, "reason": "HTTP 200", "bytes": 128, "seconds": 0.1}

    monkeypatch.setattr("app.agent.traffic_probe.curl_probe", probe)
    check = TrafficProbe(managed.context, managed.operation.host, managed.inspector)
    monkeypatch.setattr(check, "_configuration", lambda *a: {"id": "private-client"})
    if fail:
        with pytest.raises(RuntimeError):
            check.run()
    else:
        assert check.run() == []
        assert "private-client" not in json.dumps(managed.inspector.report)
    assert stopped and all(not p.exists() and not p.parent.exists() for p in paths)


def test_parameterized_plan_does_not_execute_and_revision_is_checked(settings, owned):
    calls = []

    class Executor(NodeExecutor):
        def execute(self, node, action, backup, options=None):
            calls.append(options)
            yield ExecutionEvent(message="fixture")

    container = build_container(settings, overrides={NodeExecutor: Executor()})
    with TestClient(
        create_app(settings, container=container),
        base_url="http://127.0.0.1:8765",
        headers={"X-Nodekit-Request": "1"},
    ) as client:
        saved = client.put(
            "/api/nodes/test-node", json={"yaml": yaml.safe_dump(owned.context.node)}
        ).json()["data"]
        body = {
            "action": "inbound",
            "revision": saved["revision"],
            "inbound": {
                "id": 1,
                "operation": "update",
                "port": 9443,
                "expected_fingerprint": "a" * 64,
            },
        }
        response = client.post("/api/nodes/test-node/plan", json=body)
        assert response.status_code == 200 and not calls
        assert response.json()["data"]["options"]["inbound"]["port"] == 9443
        assert (
            client.post(
                "/api/nodes/test-node/jobs", json={**body, "revision": "0" * 64}
            ).status_code
            == 409
        )
        assert not calls
        assert client.post("/api/nodes/test-node/jobs", json=body).status_code == 202
        container.resolve(TaskScheduler).close()
        assert calls[0]["inbound"]["port"] == 9443
        assert (
            client.post(
                "/api/nodes/test-node/plan",
                json={"action": "inbound", "revision": saved["revision"]},
            ).status_code
            == 422
        )

def test_add_and_remove_client_keep_existing_identity_and_backup(managed, capsys):
    manager = managed.manager
    old = copy.deepcopy(managed.items[1])
    managed.context.payload["options"]["inbound"] = {
        "id": 1,
        "operation": "add_client",
        "client_email": "extra@example.com",
        "expected_fingerprint": public_inbound(old)["fingerprint"],
    }
    manager.apply(managed.base)
    clients = managed.items[1]["settings"]["clients"]
    assert len(clients) == 2
    assert clients[0] == old["settings"]["clients"][0]
    assert clients[1]["email"] == "extra@example.com"
    assert clients[1]["id"] and clients[1]["subId"]
    assert managed.items[1]["streamSettings"] == old["streamSettings"]
    assert list(managed.base.glob("before-client-*.db"))
    assert clients[1]["id"] not in capsys.readouterr().out

    managed.context.payload["options"]["inbound"]["operation"] = "delete_client"
    manager.apply(managed.base)
    assert managed.items[1] == old


def test_client_mutations_reject_missing_duplicate_and_stale(managed):
    context = managed.context
    original = copy.deepcopy(managed.items[1])
    for operation, email in [("add_client", "client"), ("delete_client", "missing")]:
        context.payload["options"]["inbound"] = {
            "id": 1, "operation": operation, "client_email": email,
            "expected_fingerprint": public_inbound(original)["fingerprint"],
        }
        with pytest.raises(RuntimeError):
            managed.manager.apply(managed.base)
    context.payload["options"]["inbound"] = {
        "id": 1, "operation": "add_client", "client_email": "different",
        "expected_fingerprint": "0" * 64,
    }
    with pytest.raises(RuntimeError):
        managed.manager.apply(managed.base)
    assert managed.items[1] == original

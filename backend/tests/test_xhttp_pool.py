"""Regression tests for private XHTTP ingress and independent SSH session pools."""

import copy
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.agent.firewall import desired_rules, rule_spec
from app.agent.tunnel_manager import routed_template
from app.agent.tunnel_pool import pool_template
from app.agent.xhttp_manager import XHTTPManager, render_managed_site, site_for
from app.entities.job_request import JobRequest
from app.entities.network import XHTTPChange
from tests.test_subscriptions import owned as owned
from tests.test_tunnels import template


def sample_tunnels():
    return [
        {"name": "nd", "local_port": 15443},
        {"name": "nd-2", "local_port": 15444},
        {"name": "nd-3", "local_port": 15445},
    ]


def test_pool_preserves_source_and_uses_blocked_fallback():
    source = template()
    source_before = copy.deepcopy(source)
    updated, record = pool_template(
        source, "exit", "ultra", "nd-pool", sample_tunnels(), "in-xhttp"
    )
    assert source == source_before
    assert updated["outbounds"][:3] == source["outbounds"]
    assert len(updated["outbounds"]) == 6
    assert {o["settings"]["vnext"][0]["port"] for o in record["outbounds"]} == {15443, 15444, 15445}
    assert record["balancer"]["strategy"]["type"] == "roundRobin"
    assert record["balancer"]["fallbackTag"] == "blocked"
    assert record["balancer"]["selector"] == ["ssh-ultra-pool-nd-pool-"]
    assert record["rule"]["inboundTag"] == ["in-xhttp"]
    assert updated["routing"]["rules"][:2] == source["routing"]["rules"][:2]
    assert record["balancer"] in updated["routing"]["balancers"]
    assert updated["observatory"]["subjectSelector"] == ["ssh-ultra-pool-nd-pool-"]
    assert updated["observatory"]["probeInterval"] == "15s"
    repeat, repeat_record = pool_template(
        updated,
        "exit",
        "ultra",
        "nd-pool",
        sample_tunnels(),
        "in-xhttp",
        previous=record,
    )
    assert repeat == updated and repeat_record == record


def test_pool_can_migrate_exact_owned_single_without_changing_default():
    original, single_outbound, single_rule = routed_template(
        template(), "exit", sample_tunnels()[0], "ssh-ultra-nd", "in-xhttp"
    )
    new, record = pool_template(
        original,
        "exit",
        "ultra",
        "nd-pool",
        sample_tunnels(),
        "in-xhttp",
        singles=[{"name": "nd", "outbound": single_outbound, "rule": single_rule}],
    )
    assert single_outbound not in new["outbounds"]
    assert single_rule not in new["routing"]["rules"]
    assert new["routing"]["rules"][:2] == original["routing"]["rules"][:2]
    assert new["outbounds"][0]["tag"] == "direct"
    assert record["rule"] in new["routing"]["rules"]


def test_pool_rejects_foreign_changes_and_missing_failclosed_fallback():
    source, record = pool_template(
        template(), "exit", "ultra", "nd-pool", sample_tunnels(), "in-xhttp"
    )
    wrong = copy.deepcopy(source)
    wrong["outbounds"][-1]["settings"]["vnext"][0]["port"] = 12345
    with pytest.raises(ValueError):
        pool_template(
            wrong, "exit", "ultra", "nd-pool", sample_tunnels(), "in-xhttp", previous=record
        )
    unblocked = template()
    unblocked["outbounds"] = [o for o in unblocked["outbounds"] if o["tag"] != "blocked"]
    with pytest.raises(ValueError):
        pool_template(unblocked, "exit", "ultra", "nd-pool", sample_tunnels(), "in-xhttp")


def test_pool_preserves_existing_unrelated_observer():
    source = template()
    source["observatory"] = {
        "subjectSelector": ["external-"],
        "probeInterval": "20s",
        "probeUrl": "https://example.com/",
        "enableConcurrency": False,
    }
    result, _ = pool_template(source, "exit", "ultra", "nd-pool", sample_tunnels(), "in-xhttp")
    assert source["observatory"]["subjectSelector"] == ["external-"]
    assert result["observatory"]["subjectSelector"] == ["external-", "ssh-ultra-pool-nd-pool-"]


def test_multi_ssh_request_requires_valid_unique_members():
    base = {
        "action": "tunnel",
        "revision": "a" * 64,
        "tunnel": {
            "name": "nd",
            "id": 1,
            "outbound_tag": "exit",
            "expected_fingerprint": "f" * 64,
            "pool_name": "nd-pool",
            "members": ["nd", "nd-2", "nd-3"],
        },
    }
    assert JobRequest.model_validate(base).tunnel.members == ["nd", "nd-2", "nd-3"]
    for items in ([], ["nd"], ["nd", "nd"], ["nd-2", "nd"]):
        invalid = copy.deepcopy(base)
        invalid["tunnel"]["members"] = items
        with pytest.raises(ValidationError):
            JobRequest.model_validate(invalid)


def test_xhttp_site_preserves_original_path_and_h2c_private_transport():
    route = {
        "id": 2,
        "domain": "vpn.example.com",
        "path": "/xhttp-ultra/",
        "port": 10080,
        "listen": "172.30.50.1",
        "mode": "auto",
    }
    snippet = site_for(route)
    assert "@nodekit_xhttp path /xhttp-ultra/*" in snippet
    assert "handle @nodekit_xhttp" in snippet
    assert "handle_path" not in snippet
    assert "reverse_proxy h2c://172.30.50.1:10080" in snippet
    assert "flush_interval -1" in snippet
    combined = render_managed_site("sub.example.com { reverse_proxy localhost:2097 }", [route])
    assert "sub.example.com" in combined and "vpn.example.com" in combined
    assert XHTTPManager._subscriptions_only(combined, [route]).strip() == (
        "sub.example.com { reverse_proxy localhost:2097 }"
    )


def test_xhttp_validation_rejects_uncertain_adoption_and_invalid_paths():
    base = dict(
        operation="create",
        remark="xhttp-ultra",
        domain="vpn.example.com",
        port=10080,
        path="/xhttp-ultra/",
        mode="auto",
    )
    assert XHTTPChange.model_validate(base).operation == "create"
    for changed in (
        dict(path="/invalid path/"),
        dict(domain="no-dots"),
        dict(operation="update"),
        dict(operation="create", id=4),
    ):
        with pytest.raises(ValidationError):
            XHTTPChange.model_validate({**base, **changed})


def test_private_xhttp_backend_generates_only_bridge_scoped_ufw(owned, monkeypatch):
    context = owned.context
    monkeypatch.setattr(context, "directory", lambda: owned.base)
    context.node["deployment"].update(
        caddy_id="docker:shared-caddy", subscription_bind="172.30.50.1"
    )
    (owned.base / "xhttp-routes.json").write_text(
        json.dumps(
            [
                {
                    "id": 2,
                    "domain": "vpn.example.com",
                    "path": "/xhttp/",
                    "port": 10080,
                    "listen": "172.30.50.1",
                    "mode": "auto",
                }
            ]
        )
    )
    proxy = {
        "id": "docker:shared-caddy",
        "installation": "docker",
        "container": "shared-caddy",
        "bridge_networks": [
            {"gateway": "172.30.50.1", "subnet": "172.30.50.0/24", "interface": "br-example"}
        ],
    }
    report = {
        "caddy": [proxy],
        "panels": [
            {
                "id": "managed:ultra",
                "inbounds": [
                    {
                        "id": 2,
                        "enabled": True,
                        "network": "xhttp",
                        "listen": "172.30.50.1",
                        "protocol": "vless",
                        "port": 10080,
                    }
                ],
            }
        ],
        "selected_panel": "managed:ultra",
    }
    rules = desired_rules(context, report)
    assert (
        rule_spec(
            10080,
            source="172.30.50.0/24",
            destination="172.30.50.1",
            interface="br-example",
            scope="xhttp",
        )
        in rules
    )
    assert rule_spec(10080) not in rules


def test_xhttp_manager_creates_owned_site_and_inbound_without_touching_other_site(
    owned, monkeypatch, capsys
):
    context = owned.context
    context.payload["options"] = {
        "xhttp": {
            "operation": "create",
            "remark": "phone-xhttp",
            "domain": "vpn.example.com",
            "port": 10080,
            "path": "/xhttp-ultra/",
            "mode": "auto",
            "client_email": "phone",
        }
    }
    items = {}
    next_id = 2

    def request(path, data=None):
        if path == "inbounds/list":
            return copy.deepcopy(list(items.values()))
        if path == "inbounds/add":
            item = copy.deepcopy(data)
            item.update(id=next_id, tag="in-10080-tcp")
            items[next_id] = item
            return {"id": next_id}
        if path == "inbounds/get/2":
            return copy.deepcopy(items[2])
        if path == "inbounds/del/2":
            del items[2]
            return None
        if path == "server/restartXrayService":
            return None
        raise AssertionError(path)

    monkeypatch.setattr(
        "app.agent.xhttp_manager.managed_api", lambda *args: SimpleNamespace(request=request)
    )
    monkeypatch.setattr(
        "app.agent.firewall.inspect_firewall",
        lambda *args: {"state": "unavailable", "rules": [], "warnings": []},
    )
    manager = XHTTPManager(
        context,
        SimpleNamespace(require_endpoint=lambda *a: None),
        owned.operation.database,
        owned.inspector,
    )
    manager.apply(owned.base)
    assert len(items) == 1
    assert items[2]["listen"] == "127.0.0.1"
    assert "other.example.com" in owned.shared.read_text()
    assert "vpn.example.com" in owned.shared.read_text()
    assert (owned.base / "xhttp-routes.json").is_file()
    assert list(owned.base.glob("before-xhttp-*.db"))
    assert "subId" not in capsys.readouterr().out


def test_pool_migrates_two_owned_single_routes():
    original, first_out, first_rule = routed_template(
        template(), "exit", sample_tunnels()[0], "ssh-ultra-nd", "in-xhttp"
    )
    staged, second_out, second_rule = routed_template(
        original, "exit", sample_tunnels()[1], "ssh-ultra-nd-2", "in-xhttp"
    )
    updated, record = pool_template(
        staged, "exit", "ultra", "nd-pool", sample_tunnels(), "in-xhttp",
        singles=[
            {"name": "nd", "outbound": first_out, "rule": first_rule},
            {"name": "nd-2", "outbound": second_out, "rule": second_rule},
        ],
    )
    assert first_out not in updated["outbounds"]
    assert second_out not in updated["outbounds"]
    assert first_rule not in updated["routing"]["rules"]
    assert second_rule not in updated["routing"]["rules"]
    assert record["rule"] in updated["routing"]["rules"]
    assert updated["routing"]["rules"][:2] == staged["routing"]["rules"][:2]


def test_pool_refuses_modified_existing_route():
    staged, outbound, rule = routed_template(
        template(), "exit", sample_tunnels()[0], "ssh-ultra-nd", "in-xhttp"
    )
    with pytest.raises(ValueError):
        pool_template(
            staged, "exit", "ultra", "nd-pool", sample_tunnels(), "in-xhttp",
            singles=[{"name": "nd", "outbound": outbound, "rule": {**rule, "outboundTag": "direct"}}],
        )


def test_publish_existing_xhttp_host_preserves_caddy(owned, monkeypatch):
    context = owned.context
    base = owned.base
    inbound = {
        "id": 2, "port": 10080, "listen": "127.0.0.1",
        "remark": "phone", "enable": True, "protocol": "vless",
        "streamSettings": {"network": "xhttp", "security": "none",
                           "xhttpSettings": {"path": "/xhttp-ultra/", "mode": "auto"}},
    }
    from app.agent.inbound_meta import public_inbound
    request = {
        "operation": "publish", "id": 2, "port": 10080,
        "domain": "vpn.example.com", "path": "/xhttp-ultra/",
        "mode": "auto", "remark": "phone",
        "expected_fingerprint": public_inbound(inbound)["fingerprint"],
    }
    context.payload["options"] = {"xhttp": request}
    hosts = []
    def api_request(path, payload=None):
        if path == "inbounds/get/2":
            return copy.deepcopy(inbound)
        if path == "hosts/list":
            return copy.deepcopy(hosts)
        if path == "hosts/add":
            hosts.append({**payload, "groupId": "managed-host", "hosts": ["vpn.example.com:443"]})
            return None
        raise AssertionError(path)
    api = SimpleNamespace(request=api_request)
    before = owned.shared.read_bytes()
    manager = XHTTPManager(context, None, owned.operation.database, owned.inspector)
    manager.publish_host(base, api, request)
    assert owned.shared.read_bytes() == before
    assert hosts[0]["port"] == 443
    assert hosts[0]["security"] == "tls"
    assert hosts[0]["alpn"] == ["h2"]
    assert (base / "xhttp-hosts.json").is_file()
    assert list(base.glob("before-host-*.db"))

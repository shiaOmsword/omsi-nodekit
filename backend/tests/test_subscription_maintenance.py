"""The cache purge must never restart a shared service or reveal subId data."""

import base64
import copy
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.agent.inbound_meta import public_inbound
from app.agent.subscription_maintenance import (
    SubscriptionMaintenanceAgent,
    public_subscription_probe,
    share_link_count,
    verify_client,
)
from app.entities.job_request import JobRequest
from tests.test_subscriptions import owned as owned


@pytest.fixture
def maintenance(owned, monkeypatch):
    context = owned.context
    item = {
        "id": 1, "remark": "test", "protocol": "vless",
        "port": 10080, "listen": "127.0.0.1", "enable": True,
        "streamSettings": {"network": "xhttp", "security": "none", "xhttpSettings": {"path": "/xhttp/"}},
    }
    selected = owned.inspector.selected
    selected.update(
        id="docker:owned-panel-123",
        container="omsi-test-node-panel-1",
        settings={
            "subURI": "https://new.example.com:2096/sub/",
            "subEnable": "true",
        },
    )
    context.node["panel"]["installation"] = "managed"
    context.node["deployment"]["panel_runtime"] = "docker"
    context.payload["options"] = {
        "subscription_maintenance": {
            "id": 1,
            "expected_fingerprint": public_inbound(item)["fingerprint"],
            "mode": "audit",
            "client_email": "existing-client",
            "acknowledge_restart": False,
        }
    }
    calls = []
    original = {
        "Id": "owned-panel-123",
        "Name": "/omsi-test-node-panel-1",
        "Config": {"Labels": {
            "com.docker.compose.project": context.project(),
            "com.docker.compose.service": "panel",
        }},
        "State": {"Running": True},
    }
    def command(args, **kwargs):
        calls.append(args)
        if args[:2] == ["docker", "inspect"]:
            return json.dumps([original])
        if args[:2] == ["docker", "restart"]:
            return "owned-panel-123"
        raise AssertionError(args)

    def request(path):
        if path == "inbounds/get/1":
            return copy.deepcopy(item)
        if path == "clients/get/existing-client":
            return {"client": {"email": "existing-client", "subId": "private-sub-token"},
                    "inboundIds": [1]}
        raise AssertionError(path)

    monkeypatch.setattr(context, "command", command)
    monkeypatch.setattr("app.agent.subscription_maintenance.managed_api",
                        lambda *args: SimpleNamespace(request=request))
    monkeypatch.setattr("app.agent.subscription_maintenance.public_subscription_probe",
                        lambda *args: (200, 5, "no-store"))
    monkeypatch.setattr("app.agent.subscription_maintenance.dns_resolve",
                        lambda *args: ["203.0.113.10"])
    monkeypatch.setattr("app.agent.subscription_maintenance.time.sleep", lambda _: None)
    manager = SubscriptionMaintenanceAgent(
        context, owned.operation.host, owned.operation.database, owned.inspector
    )
    return SimpleNamespace(context=context, base=owned.base, manager=manager,
                           inspector=owned.inspector, calls=calls, original=original)


def test_audit_is_read_only_and_never_logs_private_subscription(maintenance, capsys):
    manager = maintenance.manager
    before = maintenance.inspector.database().read_bytes()
    manager.apply(maintenance.base)
    assert maintenance.inspector.database().read_bytes() == before
    assert maintenance.calls == []
    assert not list(maintenance.base.glob("before-sub-cache-reset-*.db"))
    log = capsys.readouterr().out
    assert "5 share links" in log
    assert "private-sub-token" not in log
    assert "id:" not in log


def test_purge_restarts_only_owned_panel_and_saves_snapshot(maintenance, capsys):
    maintenance.context.payload["options"]["subscription_maintenance"].update(
        mode="clear_server_cache", acknowledge_restart=True
    )
    maintenance.manager.apply(maintenance.base)
    assert maintenance.calls == [
        ["docker", "inspect", "omsi-test-node-panel-1"],
        ["docker", "restart", "--time", "10", "owned-panel-123"],
    ]
    assert list(maintenance.base.glob("before-sub-cache-reset-*.db"))
    assert "private-sub-token" not in capsys.readouterr().out


@pytest.mark.parametrize("tamper", ["project", "service", "id", "running", "native"])
def test_purge_rejects_other_containers_and_native_panels_before_restart(maintenance, tamper):
    maintenance.context.payload["options"]["subscription_maintenance"].update(
        mode="clear_server_cache", acknowledge_restart=True
    )
    if tamper == "project":
        maintenance.original["Config"]["Labels"]["com.docker.compose.project"] = "shared-caddy"
    if tamper == "service":
        maintenance.original["Config"]["Labels"]["com.docker.compose.service"] = "caddy"
    if tamper == "id":
        maintenance.original["Id"] = "foreign-panel"
    if tamper == "running":
        maintenance.original["State"]["Running"] = False
    if tamper == "native":
        maintenance.context.node["deployment"]["panel_runtime"] = "native"
    with pytest.raises(RuntimeError, match="only available"):
        maintenance.manager.apply(maintenance.base)
    assert not any(call[:2] == ["docker", "restart"] for call in maintenance.calls)
    assert not list(maintenance.base.glob("before-sub-cache-reset-*.db"))


def test_client_from_other_inbound_is_rejected():
    api = SimpleNamespace(request=lambda path: {
        "client": {"email": "customer", "subId": "private-token"}, "inboundIds": [99],
    })
    with pytest.raises(RuntimeError, match="does not belong"):
        verify_client(api, 1, "customer")


def test_audit_and_purge_require_distinct_acknowledgment():
    original = {
        "action": "subscription_maintenance",
        "revision": "f" * 64,
        "subscription_maintenance": {
            "id": 1,
            "expected_fingerprint": "a" * 64,
            "mode": "audit",
        },
    }
    assert JobRequest.model_validate(original).subscription_maintenance.mode == "audit"
    for request in (
        {"mode": "clear_server_cache"},
        {"mode": "audit", "acknowledge_restart": True},
        {"mode": "clear_server_cache", "acknowledge_restart": False},
    ):
        with pytest.raises(ValidationError):
            JobRequest.model_validate({
                **original, "subscription_maintenance": {
                    **original["subscription_maintenance"], **request,
                },
            })
    assert JobRequest.model_validate({
        **original, "subscription_maintenance": {
            **original["subscription_maintenance"],
            "mode": "clear_server_cache", "acknowledge_restart": True,
        },
    }).subscription_maintenance.acknowledge_restart


def test_only_local_public_https_is_probe_target_and_bodies_stay_private(monkeypatch):
    class Response:
        status = 200
        headers = {"Cache-Control": "no-store"}
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self, limit):
            assert limit < 2 * 1024 * 1024
            return base64.b64encode(b"vless://private-uuid@vpn.example.com:443#secret")

    calls = []
    class Opener:
        def open(self, request, timeout):
            calls.append(request.full_url)
            assert timeout <= 15
            return Response()

    monkeypatch.setattr("app.agent.subscription_maintenance.urllib.request.build_opener",
                        lambda *args: Opener())
    context = SimpleNamespace(
        node={"caddy": {"enabled": True, "domain": "new.example.com", "https_port": 2096},
              "panel": {"subscription_path": "/sub/"}},
        policy={"http_timeout": 10},
    )
    assert public_subscription_probe(context, "private-sub-token") == (200, 1, "no-store")
    assert calls == ["https://new.example.com:2096/sub/private-sub-token"]
    assert share_link_count(b"vless://private@host:443\nvmess://another-token") == 2

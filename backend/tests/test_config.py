import pytest
import yaml

from app.entities import Node
from framework.entities import ValidationError


def test_example_is_valid(factory):
    from pathlib import Path

    assert (
        factory.from_yaml((Path(__file__).parents[1] / "config/config-example.yaml").read_text()).id
        == "moscow-1"
    )


@pytest.mark.parametrize("text", ["", "[]", "hello", "- a\n- b", "x: ["])
def test_reject_non_mapping_yaml(text, factory):
    with pytest.raises((ValidationError, yaml.YAMLError)):
        factory.from_yaml(text)


@pytest.mark.parametrize(
    "image", ["ghcr.io/mhsanaei/3x-ui", "ghcr.io/mhsanaei/3x-ui:latest", "x:1;reboot"]
)
def test_require_pinned_images(node, image):
    data = node.model_dump()
    data["panel"]["image"] = image
    with pytest.raises(ValueError):
        Node.model_validate(data)


def test_docker_host_network_preserves_tunnel_localhost(node, renderer):
    compose = yaml.safe_load(renderer.compose_config(node))
    assert compose["services"]["panel"]["network_mode"] == "host"
    assert compose["services"]["panel"]["environment"]["XUI_ENABLE_FAIL2BAN"] == "false"


def test_two_ports_generate_separate_ssh_processes(node, renderer):
    data = node.model_dump()
    data["tunnels"] = [
        {"name": "gb-22", "host": "203.0.113.20", "local_port": 15443},
        {"name": "gb-2222", "host": "203.0.113.20", "ssh_port": 2222, "local_port": 15444},
    ]
    files = renderer.artifacts(Node.model_validate(data))
    assert "-p 22 " in files["omsi-test-node-gb-22.service"]
    assert "-p 2222 " in files["omsi-test-node-gb-2222.service"]
    assert "StrictHostKeyChecking=yes" in files["omsi-test-node-gb-22.service"]
    assert "127.0.0.1:15444:127.0.0.1:443" in files["omsi-test-node-gb-2222.service"]


@pytest.mark.parametrize(
    "change",
    [
        {"panel": {"port": 443}},
        {"panel": {"subscription_port": 2053}},
        {"ssh": {"host": "-oProxyCommand=evil"}},
        {"unknown_option": "silently ignored?"},
        {"tunnels": [{"name": "x", "host": "a", "identity_file": "/home/x/%h"}]},
        {"tunnels": [{"name": "x", "host": "a"}, {"name": "y", "host": "a"}]},
    ],
)
def test_reject_unsafe_or_colliding_config(node, change):
    data = node.model_dump()
    for key, value in change.items():
        if key in {"panel", "ssh"}:
            data[key].update(value)
        else:
            data[key] = value
    with pytest.raises(ValueError):
        Node.model_validate(data)


def test_caddy_routes_subscriptions_only_and_preserves_xray_443(node, renderer):
    data = node.model_dump()
    data["caddy"]["enabled"] = True
    files = renderer.artifacts(Node.model_validate(data))
    assert "https://vpn.example.com:2096" in files["Caddyfile"]
    assert "disable_tlsalpn_challenge" in files["Caddyfile"]
    assert "127.0.0.1:2097" in files["Caddyfile"]
    assert "respond 404" in files["Caddyfile"]
    assert "caddy-data:/data" in files["compose.yaml"]


def test_plan_does_not_claim_end_to_end_without_probe(node, renderer):
    assert any("not configured" in step for step in renderer.plan(node, "doctor")["steps"])

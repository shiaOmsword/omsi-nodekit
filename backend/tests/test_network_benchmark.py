from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.agent.network_benchmark import assess, download_sample, ping_metrics, tcp_counters
from app.create_app import create_app
from app.entities import JobRequest


def test_filtered_icmp_is_unknown_not_healthy():
    metrics = ping_metrics("10 packets transmitted, 0 received, 100% packet loss")
    assert metrics == {"loss_percent": 100, "rtt_ms": None, "jitter_ms": None}
    assert ping_metrics("ping: not permitted")["loss_percent"] is None
    valid = ping_metrics("rtt min/avg/max/mdev = 20.1/31.2/42.3/9.4 ms")
    assert valid["rtt_ms"] == 31.2 and valid["jitter_ms"] == 9.4
    states = assess(
        metrics, dict(min_mbps=100, max_rtt_ms=80, max_jitter_ms=10, max_loss_percent=1)
    )
    assert states["loss_percent"] == "warning" and states["mbps"] == "unavailable"


def test_counters_use_matching_tcp_headers(tmp_path):
    path = tmp_path / "snmp"
    path.write_text("Ip: OutSegs\nIp: 700\nTcp: OutSegs RetransSegs\nTcp: 1000 12\n")
    assert tcp_counters(path) == {"OutSegs": 1000, "RetransSegs": 12}


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/data",
        "https://user:password@example.com/data",
        "https://example.com/data#token",
        "https://example.com:99999/data",
        "https://example.com/data\r\nHeader: 1",
    ],
)
def test_unsafe_targets_are_rejected(url):
    with pytest.raises(ValueError):
        JobRequest(action="network_benchmark", revision="a" * 64, network_benchmark={"url": url})


def test_download_is_bounded_and_never_accepts_small_error_pages(monkeypatch):
    size = [1024 * 1024 * 100]
    closed = []

    class Response:
        status = 200

        def getheader(self, name, default=None):
            return default

        def read1(self, count):
            actual = min(size[0], count)
            size[0] -= actual
            return b"x" * actual

    response = Response()
    connection = SimpleNamespace(
        connect=lambda: None,
        request=lambda *a, **k: None,
        getresponse=lambda: response,
        close=lambda: closed.append(True),
        sock=None,
    )
    monkeypatch.setattr(
        "app.agent.network_benchmark.http.client.HTTPSConnection", lambda *a, **k: connection
    )
    result = download_sample("https://example.com/data", 2 * 1024 * 1024)
    assert result["bytes"] == 2 * 1024 * 1024 and result["capped"]
    size[0] = 500
    with pytest.raises(ValueError):
        download_sample("https://example.com/data", 2 * 1024 * 1024)
    assert len(closed) == 2


def test_bbr_and_benchmark_preview_preserve_options_without_running(settings, node_yaml):
    with TestClient(
        create_app(settings), base_url="http://127.0.0.1:8765", headers={"X-Nodekit-Request": "1"}
    ) as client:
        record = client.put("/api/nodes/test-node", json={"yaml": node_yaml}).json()["data"]
        for action, options in [
            ("tcp_tuning", {"algorithm": "bbr", "expected_fingerprint": "b" * 64}),
            ("network_benchmark", {"url": "https://example.com/test.bin"}),
        ]:
            response = client.post(
                "/api/nodes/test-node/plan",
                json={"action": action, "revision": record["revision"], action: options},
            )
            assert response.status_code == 200, response.text
            assert response.json()["data"]["options"][action].items() >= options.items()
        assert client.get("/api/jobs").json()["data"] == []

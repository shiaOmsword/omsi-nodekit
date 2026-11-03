"""Bounded direct-path measurements. No services or network settings are changed."""

import http.client
import re
import shutil
import socket
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from framework.messages import MessageKey
from framework.messages import text as message_text

from .tcp_tuning import TCPConfigurator


def tcp_counters(path=Path("/proc/net/snmp")):
    try:
        lines = path.read_text().splitlines()
        for header, values in zip(lines, lines[1:]):
            if header.startswith("Tcp:") and values.startswith("Tcp:"):
                return dict(zip(header.split()[1:], map(int, values.split()[1:])))
    except (OSError, ValueError):
        pass
    return {}


def ping_metrics(output):
    loss = re.search(r"([\d.]+)% packet loss", output)
    rtt = re.search(r"(?:rtt|round-trip).*?= ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)", output)
    return {
        "loss_percent": float(loss[1]) if loss else None,
        "rtt_ms": float(rtt[2]) if rtt else None,
        "jitter_ms": float(rtt[4]) if rtt else None,
    }


def download_sample(url, byte_limit, timeout=20):
    target = urlsplit(url)
    connection = http.client.HTTPSConnection(target.hostname, target.port or 443, timeout=timeout)
    started = time.monotonic()
    try:
        connection.connect()
        connected = time.monotonic()
        connection.request(
            "GET",
            (target.path or "/") + ("?" + target.query if target.query else ""),
            headers={
                "User-Agent": "OMSI-Nodekit-benchmark",
                "Accept-Encoding": "identity",
                "Cache-Control": "no-cache",
                "Connection": "close",
            },
        )
        response = connection.getresponse()
        headers_at = time.monotonic()
        if (
            response.status != 200
            or response.getheader("Content-Encoding", "identity") != "identity"
        ):
            raise ValueError()
        received = 0
        while received < byte_limit:
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError()
            if connection.sock:
                connection.sock.settimeout(remaining)
            chunk = response.read1(min(65536, byte_limit - received))
            if not chunk:
                break
            received += len(chunk)
        finished = time.monotonic()
        # A small HTML error page must never be presented as a speed benchmark.
        if received < 1024 * 1024:
            raise ValueError()
        elapsed = finished - started
        return {
            "bytes": received,
            "elapsed_ms": round(elapsed * 1000, 2),
            "connect_tls_ms": round((connected - started) * 1000, 2),
            "ttfb_ms": round((headers_at - connected) * 1000, 2),
            "mbps": round(received * 8 / elapsed / 1_000_000, 3),
            "capped": received == byte_limit,
        }
    finally:
        connection.close()


def assess(metrics, thresholds):
    rules = {
        "mbps": (thresholds["min_mbps"], True),
        "rtt_ms": (thresholds["max_rtt_ms"], False),
        "jitter_ms": (thresholds["max_jitter_ms"], False),
        "loss_percent": (thresholds["max_loss_percent"], False),
    }
    return {
        name: "unavailable"
        if metrics.get(name) is None
        else "ok"
        if (metrics[name] >= limit if minimum else metrics[name] <= limit)
        else "warning"
        for name, (limit, minimum) in rules.items()
    }


class NetworkBenchmark:
    def __init__(self, context, inspector):
        self.context, self.inspector = context, inspector

    def run(self):
        options = self.context.payload["options"]["network_benchmark"]
        url = options["url"]
        target = urlsplit(url)
        before = tcp_counters()
        metrics = {"rtt_ms": None, "jitter_ms": None, "loss_percent": None, "mbps": None}
        warnings, samples = [], []
        dns_started = time.monotonic()
        try:
            addresses = sorted(
                {
                    item[4][0]
                    for item in socket.getaddrinfo(
                        target.hostname, target.port or 443, type=socket.SOCK_STREAM
                    )
                }
            )
            dns_ms = round((time.monotonic() - dns_started) * 1000, 2)
        except OSError:
            addresses, dns_ms = [], None
        # LC_ALL is explicit: parsers must not depend on the VPS locale.
        if addresses and shutil.which("ping"):
            try:
                result = self.context.runner.completed(
                    [
                        "env",
                        "LC_ALL=C",
                        "ping",
                        "-n",
                        "-c",
                        "10",
                        "-i",
                        "0.2",
                        "-W",
                        "2",
                        "--",
                        addresses[0],
                    ],
                    timeout=25,
                )
                metrics.update(ping_metrics(result.stdout))
            except (OSError, RuntimeError):
                warnings.append("icmp_unavailable")
        else:
            warnings.append("icmp_unavailable")
        for _ in range(options["attempts"]):
            try:
                samples.append(download_sample(url, options["sample_bytes"]))
            except (OSError, ValueError, http.client.HTTPException):
                warnings.append("https_sample_failed")
        if len(samples) == options["attempts"]:
            metrics["mbps"] = round(statistics.median(s["mbps"] for s in samples), 3)
        after = tcp_counters()
        sent = after.get("OutSegs", 0) - before.get("OutSegs", 0)
        retrans = after.get("RetransSegs", 0) - before.get("RetransSegs", 0)
        tcp = TCPConfigurator(self.context).inspect()
        report = {
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "scope": "vps_direct_https_download",
            "profile": options,
            "resolved_addresses": addresses,
            "dns_ms": dns_ms,
            "algorithm": tcp["current"] if tcp else None,
            "samples": samples,
            "metrics": metrics,
            "assessment": assess(metrics, options),
            "warnings": sorted(set(warnings)),
            # These are HOST-WIDE deltas, not loss on this particular connection.
            "host_tcp": {"out_segments": max(0, sent), "retrans_segments": max(0, retrans)}
            if before and after and sent >= 0 and retrans >= 0
            else None,
        }
        self.inspector.report["network_benchmark"] = report
        self.inspector.publish()
        self.context.emit(message_text(MessageKey.NETWORK_BENCHMARK_COMPLETED))

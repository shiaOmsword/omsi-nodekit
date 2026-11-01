"""Tests for owned TCP congestion settings; no host sysctl is changed."""

from types import SimpleNamespace

import pytest

from app.agent.tcp_tuning import TCPConfigurator
from app.entities import JobRequest


@pytest.fixture
def tcp(tmp_path):
    proc = tmp_path / "proc"
    proc.mkdir()
    current = proc / "control"
    available = proc / "available"
    current.write_text("cubic\n")
    available.write_text("reno cubic\n")
    sysctl = tmp_path / "sysctl.d" / "99-zz-omsi-nodekit-tcp.conf"
    module = tmp_path / "modules-load.d" / "omsi-nodekit-tcp.conf"
    sysctl.parent.mkdir()
    module.parent.mkdir()
    commands = []
    events = []

    def command(args):
        commands.append(args)
        if args[:2] == ["modprobe", "tcp_bbr"]:
            available.write_text("reno cubic bbr\n")
        if args[:2] == ["sysctl", "-w"]:
            current.write_text(args[2].partition("=")[2] + "\n")

    context = SimpleNamespace(
        payload={"options": {}},
        command=command,
        emit=lambda *args: events.append(args),
    )
    manager = TCPConfigurator(
        context,
        current_path=current,
        available_path=available,
        sysctl_path=sysctl,
        module_path=module,
    )
    return SimpleNamespace(
        manager=manager,
        context=context,
        current=current,
        available=available,
        sysctl=sysctl,
        module=module,
        commands=commands,
        events=events,
    )


def select(tcp, algorithm="bbr"):
    tcp.context.payload["options"]["tcp_tuning"] = {
        "algorithm": algorithm,
        "expected_fingerprint": tcp.manager.inspect()["fingerprint"],
    }


def test_bbr_persists_without_touching_services_and_is_idempotent(tcp):
    select(tcp)
    tcp.manager.apply()
    assert tcp.current.read_text() == "bbr\n"
    assert tcp.sysctl.read_text().splitlines()[-1].endswith(" = bbr")
    assert tcp.module.read_text().splitlines()[-1] == "tcp_bbr"
    assert not any("systemctl" in args for args in tcp.commands)
    assert tcp.manager.inspect()["managed_algorithm"] == "bbr"
    before = (tcp.sysctl.read_bytes(), tcp.module.read_bytes())
    select(tcp)
    tcp.manager.apply()
    assert (tcp.sysctl.read_bytes(), tcp.module.read_bytes()) == before


def test_cubic_restores_default_and_removes_owned_module_file(tcp):
    select(tcp)
    tcp.manager.apply()
    select(tcp, "cubic")
    tcp.manager.apply()
    assert tcp.current.read_text() == "cubic\n"
    assert not tcp.module.exists()
    assert tcp.manager.inspect()["managed_algorithm"] == "cubic"


def test_stale_snapshot_never_modifies_host(tcp):
    select(tcp)
    tcp.current.write_text("reno\n")
    with pytest.raises(RuntimeError, match="refresh"):
        tcp.manager.apply()
    assert not tcp.sysctl.exists() and not tcp.commands


@pytest.mark.parametrize("foreign", ["custom text\n", "symlink"])
def test_operator_file_is_preserved(tcp, foreign):
    if foreign == "symlink":
        target = tcp.sysctl.parent / "foreign.conf"
        target.write_text("manual\n")
        tcp.sysctl.symlink_to(target)
    else:
        tcp.sysctl.write_text(foreign)
    select(tcp)
    with pytest.raises(RuntimeError, match="foreign"):
        tcp.manager.apply()
    assert not tcp.commands
    assert tcp.sysctl.is_symlink() if foreign == "symlink" else tcp.sysctl.read_text() == foreign


def test_failure_reverts_owned_files_and_live_algorithm(tcp):
    original = tcp.context.command

    def fail_after_mutation(args):
        original(args)
        if args[:2] == ["sysctl", "-w"] and args[2].endswith("=bbr"):
            raise RuntimeError("do-not-log-secret")

    tcp.context.command = fail_after_mutation
    select(tcp)
    with pytest.raises(RuntimeError, match="rollback"):
        tcp.manager.apply()
    assert tcp.current.read_text() == "cubic\n"
    assert not tcp.sysctl.exists()
    assert not tcp.module.exists()


def test_module_missing_is_reported_and_cleaned_up(tcp):
    tcp.context.command = lambda args: None
    select(tcp)
    with pytest.raises(RuntimeError, match="rollback"):
        tcp.manager.apply()
    assert not tcp.sysctl.exists()


def test_job_schema_requires_typed_snapshot():
    with pytest.raises(ValueError):
        JobRequest(action="tcp_tuning", revision="a" * 64)
    with pytest.raises(ValueError):
        JobRequest(
            action="tcp_tuning",
            revision="a" * 64,
            tcp_tuning={"algorithm": "invalid", "expected_fingerprint": "b" * 64},
        )
    value = JobRequest(
        action="tcp_tuning",
        revision="a" * 64,
        tcp_tuning={"algorithm": "bbr", "expected_fingerprint": "b" * 64},
    )
    assert value.tcp_tuning.algorithm == "bbr"

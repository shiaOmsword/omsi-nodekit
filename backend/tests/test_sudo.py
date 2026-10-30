import ast
import json
import shlex
import shutil
import subprocess
import sys
from dataclasses import replace

import pytest
import yaml

from app.entities import Node
from app.infrastructure.auth import SudoPasswordResolver
from app.infrastructure.execution import RemoteAgentBuilder
from app.ports import BackupFiles, NodeExecutor
from framework.entities import ConfigurationError, ValidationError
from framework.messages import MessageKey, text
from framework.network import (
    CommandRunner,
    ProcessError,
    SSHClient,
    SSHConnection,
    SSHOptions,
    SudoInput,
)

PASSWORD = "Sudo-Only_тест '$()`; + / 73!"


@pytest.fixture
def connection(tmp_path):
    identity, hosts = tmp_path / "identity", tmp_path / "known_hosts"
    identity.touch()
    hosts.touch()
    return SSHConnection("203.0.113.10", "omsi", 22, str(identity), str(hosts), sudo=True)


@pytest.fixture
def options():
    return SSHOptions("ssh", 10, 10, 3, "python3 -", "sudo -n python3 -")


class LocalSudoRunner:
    """Exercise the real decoder in a subprocess, modelling sudo consuming one line or none."""

    def __init__(self, *, reads_password=True, reject=False, password=PASSWORD):
        self.reads_password = reads_password
        self.reject = reject
        self.password = password
        self.args = None
        self.content = None

    def stream(self, args, content, *, timeout):
        self.args, self.content = args, content
        command = shlex.split(args[-1])
        assert command[:6] == ["sudo", "-S", "-p", "", "--", "python3"]
        assert command[6] == "-c"
        assert PASSWORD not in repr(args)
        if self.reject:
            yield f"sudo: fixture rejected {PASSWORD}\n"
            raise ProcessError("exit 1")
        if self.reads_password:
            supplied, content = content.split("\n", 1)
            assert supplied == self.password
        yield from CommandRunner().stream(
            [sys.executable, "-c", command[7]], content, timeout=timeout
        )


@pytest.mark.parametrize("reads_password", [True, False])
def test_password_and_source_are_separate_even_with_cached_or_nopasswd_sudo(
    connection, options, reads_password
):
    runner = LocalSudoRunner(reads_password=reads_password)
    client = SSHClient(runner, options)
    connection = replace(connection, sudo_password=PASSWORD)
    # Includes enough source to exceed Windows command-line limits if accidentally put in argv.
    script = "# payload\n" * 5000 + "print('agent executed')\n"
    assert list(client.execute(connection, script, timeout=10)) == ["agent executed\n"]
    assert len(runner.args[-1]) < 3000
    assert PASSWORD not in repr(connection)
    assert script not in repr(runner.args)


def test_rejected_password_is_redacted_and_returns_actionable_error(connection, options):
    client = SSHClient(LocalSudoRunner(reject=True), options)
    stream = client.execute(
        replace(connection, sudo_password=PASSWORD), "print('must not run')", timeout=10
    )
    output = next(stream)
    assert PASSWORD not in output and "[REDACTED]" in output
    with pytest.raises(ProcessError, match="sudo password") as error:
        list(stream)
    assert PASSWORD not in str(error.value)


def test_error_after_authentication_keeps_agent_failure_instead_of_claiming_bad_password(
    connection, options
):
    client = SSHClient(LocalSudoRunner(), options)
    stream = client.execute(
        replace(connection, sudo_password=PASSWORD), "raise SystemExit(7)", timeout=10
    )
    with pytest.raises(ProcessError, match="exit 7"):
        list(stream)


def test_missing_auth_marker_never_counts_as_success(connection, options):
    class EmptyRunner:
        def stream(self, *args, **kwargs):
            return iter(())

    with pytest.raises(ProcessError, match="privileged agent"):
        list(
            SSHClient(EmptyRunner(), options).execute(
                replace(connection, sudo_password=PASSWORD), "pass", timeout=1
            )
        )


def test_root_and_passwordless_sudo_keep_original_transport(connection, options):
    class Runner:
        def stream(self, args, content, **kwargs):
            assert content == "pass\n"
            yield args[-1]

    client = SSHClient(Runner(), options)
    assert list(client.execute(replace(connection, sudo=False), "pass\n", timeout=1)) == [
        "python3 -"
    ]
    assert list(client.execute(connection, "pass\n", timeout=1)) == ["sudo -n python3 -"]


@pytest.mark.parametrize("password", ["", "bad\nline", "bad\rline", "bad\0line", "x" * 4097])
def test_invalid_password_fails_without_exposing_input(factory, node, password):
    config = node.model_dump(mode="json")
    config["ssh"].update(sudo=True, sudo_password=password)
    with pytest.raises(ValidationError) as error:
        factory.from_yaml(yaml.safe_dump(config))
    assert error.value.details
    assert error.value.details[0]["field"] == "ssh.sudo_password"
    with pytest.raises(ProcessError):
        SudoInput(password)


def test_password_source_requires_sudo_and_cannot_be_ambiguous(factory, node):
    config = node.model_dump(mode="json")
    config["ssh"]["sudo_password"] = PASSWORD
    with pytest.raises(ValidationError):
        factory.from_yaml(yaml.safe_dump(config, allow_unicode=True))
    config["ssh"].update(sudo=True, sudo_password_env="OMSI_SUDO_PASSWORD")
    with pytest.raises(ValidationError):
        factory.from_yaml(yaml.safe_dump(config, allow_unicode=True))


def test_inline_and_environment_resolution_are_local_and_hidden(container, node, monkeypatch):
    resolver = container.resolve(SudoPasswordResolver)
    config = node.model_dump(mode="json")
    config["ssh"].update(sudo=True, sudo_password=PASSWORD)
    inline = Node.model_validate(config)
    assert resolver.resolve(inline.ssh) == PASSWORD
    assert PASSWORD not in repr(inline)
    assert PASSWORD not in inline.model_dump_json()
    assert inline.model_dump(mode="json")["ssh"]["sudo_password"] == "**********"
    config["ssh"].pop("sudo_password")
    config["ssh"]["sudo_password_env"] = "OMSI_NODEKIT_TEST_SUDO"
    reference = Node.model_validate(config)
    monkeypatch.delenv("OMSI_NODEKIT_TEST_SUDO", raising=False)
    with pytest.raises(ConfigurationError, match="OMSI_NODEKIT_TEST_SUDO"):
        resolver.resolve(reference.ssh)
    monkeypatch.setenv("OMSI_NODEKIT_TEST_SUDO", PASSWORD)
    assert resolver.resolve(reference.ssh) == PASSWORD
    monkeypatch.setenv("OMSI_NODEKIT_TEST_SUDO", "bad\nline")
    with pytest.raises(ConfigurationError):
        resolver.resolve(reference.ssh)


def test_password_is_absent_from_bundle_and_backup_manifests(container, node, db_file):
    config = node.model_dump(mode="json")
    config["ssh"].update(sudo=True, sudo_password=PASSWORD)
    node = Node.model_validate(config)
    script = container.resolve(RemoteAgentBuilder).build(node, "check")
    call = next(
        item
        for item in ast.walk(ast.parse(script))
        if isinstance(item, ast.Call)
        and isinstance(item.func, ast.Attribute)
        and item.func.attr == "loads"
    )
    payload = json.loads(call.args[0].value)
    assert "sudo_password" not in payload["node"]["ssh"]
    assert "sudo_password_env" not in payload["node"]["ssh"]
    assert PASSWORD not in script
    assert "sudo_password" not in node.export_config()["ssh"]
    files = container.resolve(BackupFiles)
    files.write_manifest("test", node)
    manifest = files.path("test", manifest=True).read_text(encoding="utf-8")
    assert PASSWORD not in manifest and "sudo_password" not in manifest


def test_executor_passes_real_secret_only_to_local_connection(container, node, monkeypatch):
    executor = container.resolve(NodeExecutor)
    config = node.model_dump(mode="json")
    config["ssh"].update(sudo=True, sudo_password=PASSWORD)
    node = Node.model_validate(config)

    def execute(connection, script, **kwargs):
        assert connection.sudo_password == PASSWORD
        assert PASSWORD not in script
        yield '{"message":"agent ran"}\n'

    monkeypatch.setattr(executor.ssh, "execute", execute)
    events = list(executor.execute(node, "check", None))
    assert events[-1].message == "agent ran"
    assert PASSWORD not in repr(events)


def test_short_password_does_not_redact_or_corrupt_authenticated_backup_output(connection, options):
    runner = LocalSudoRunner(password="a")
    script = 'print(\'{"backup":"YWFhYQ==","message":"a data a"}\')'
    lines = list(
        SSHClient(runner, options).execute(
            replace(connection, sudo_password="a"), script, timeout=10
        )
    )
    assert lines == ['{"backup":"YWFhYQ==","message":"a data a"}\n']


def test_typed_api_masks_password_and_validation_errors_do_not_echo_it(settings, container, node):
    from fastapi.testclient import TestClient

    from app.create_app import create_app

    config = node.model_dump(mode="json")
    config["ssh"].update(sudo=True, sudo_password=PASSWORD)
    with TestClient(
        create_app(settings, container=container),
        base_url="http://127.0.0.1:8765",
        headers={"X-Nodekit-Request": "1"},
    ) as client:
        response = client.post(
            "/api/config/validate", json={"yaml": yaml.safe_dump(config, allow_unicode=True)}
        )
        assert response.status_code == 200
        assert response.json()["data"]["node"]["ssh"]["sudo_password"] == "**********"
        assert PASSWORD not in response.text
        config["ssh"]["sudo_password"] = PASSWORD + "\n"
        rejected = client.post(
            "/api/config/validate", json={"yaml": yaml.safe_dump(config, allow_unicode=True)}
        )
        assert rejected.status_code == 422
        assert PASSWORD not in rejected.text


def test_decoder_rejects_invalid_framing_without_evaluating_password():
    protocol = SudoInput("secret-marker-test")
    args = shlex.split(protocol.command(SudoInput.DEFAULT_COMMAND))
    process = subprocess.run(
        [sys.executable, "-c", args[-1]],
        input=b"not-a-marker\nstill-not-a-marker\n",
        capture_output=True,
        timeout=10,
    )
    assert process.returncode == 1
    assert json.loads(process.stdout)["message"] == text(MessageKey.SUDO_PROTOCOL_INVALID)
    assert b"Traceback" not in process.stderr


@pytest.mark.skipif(
    sys.platform != "linux" or not shutil.which("sudo"),
    reason="Real sudo fixture needs Linux and sudo",
)
def test_real_nopasswd_sudo_keeps_password_out_of_python_source(connection, options):
    check = subprocess.run(["sudo", "-n", "true"], capture_output=True, timeout=10)
    if check.returncode:
        pytest.skip("Current test user has no usable passwordless sudo")

    class Runner:
        def stream(self, args, content, *, timeout):
            return CommandRunner().stream(shlex.split(args[-1]), content, timeout=timeout)

    result = list(
        SSHClient(Runner(), options).execute(
            replace(connection, sudo_password=PASSWORD),
            "import os;print('root=' + str(os.geteuid() == 0))",
            timeout=10,
        )
    )
    assert result == ["root=True\n"]

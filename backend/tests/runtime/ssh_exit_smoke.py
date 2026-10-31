"""Opt-in Linux/root smoke: real 3x-ui + Caddy/XHTTP + SSH + REALITY return traffic.

Run with PYTHONPATH=src from backend. All credentials and listeners are temporary;
no installed panel, existing SSH daemon, or public VPS is used. systemctl is simulated,
but its generated ExecStart is executed by real OpenSSH. The OpenSSH server backend
requires /run/sshd; a Paramiko fixture is available in restricted containers.
Paramiko mode simulates the root runuser readability check as os.access.
"""

import argparse
import json
import os
import re
import shlex
import signal
import socket
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

from app.agent.context import AgentContext
from app.agent.database import PanelDatabase
from app.agent.host import HostEnvironment
from app.agent.inbound_meta import public_inbound
from app.agent.panel_api import PanelAPI
from app.agent.tunnel_manager import TunnelManager
from app.config import Settings
from app.entities import Node
from app.infrastructure.rendering import NodeArtifacts
from framework.entities import YamlCodec


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait(check):
    for _ in range(100):
        if check():
            return
        time.sleep(0.1)
    raise RuntimeError("Fixture readiness failed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("xray", "caddy", "panel"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--sshd", type=Path)
    parser.add_argument("--ssh-backend", choices=("openssh", "paramiko"), default="openssh")
    args = parser.parse_args()
    if os.name != "posix" or os.geteuid() != 0:
        parser.error("Use a disposable Linux root environment")
    if args.ssh_backend == "openssh" and (not args.sshd or not Path("/run/sshd").is_dir()):
        parser.error("OpenSSH backend requires --sshd and /run/sshd")
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix="nodekit-ssh-runtime-") as folder:
        root = Path(folder)
        base = root / "smoke"
        for name in ("db", "runtime/bin", "logs", "cert", "units"):
            (base / name).mkdir(parents=True)
        for name in ("xray-linux-amd64", "geoip.dat", "geosite.dat"):
            source = args.xray if name.startswith("xray-") else args.xray.parent / name
            (base / "runtime/bin" / name).symlink_to(source.resolve())
        jobs, handles = [], []

        def run(command, env=None):
            return subprocess.run(
                command, env=env, cwd=root, capture_output=True, text=True, check=True, timeout=15
            ).stdout

        def start(command, name, env=None):
            log = (root / (name + ".log")).open("wb")
            handles.append(log)
            process = subprocess.Popen(
                command, env=env, cwd=root, stdout=log, stderr=log, start_new_session=True
            )
            jobs.append(process)
            return process

        def stop(process):
            if process and process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)

        ssh_port, forward_port, exit_port, ingress_port, web_port, https_port, socks_port = [
            port() for _ in range(7)
        ]
        cert, key = root / "cert.pem", root / "key.pem"
        run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "ec",
                "-pkeyopt",
                "ec_paramgen_curve:prime256v1",
                "-nodes",
                "-days",
                "1",
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=DNS:localhost,IP:127.0.0.1",
                "-keyout",
                str(key),
                "-out",
                str(cert),
            ]
        )
        hostkey, identity, known = root / "ssh_host", root / "ssh_client", root / "known_hosts"
        for path in (hostkey, identity):
            run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(path)])
        known.write_text(f"[127.0.0.1]:{ssh_port} " + hostkey.with_suffix(".pub").read_text())
        ssh_config = root / "sshd_config"
        ssh_config.write_text(f"""Port {ssh_port}
ListenAddress 127.0.0.1
HostKey {hostkey}
PidFile {root}/sshd.pid
AuthorizedKeysFile {identity}.pub
StrictModes no
PermitRootLogin prohibit-password
PasswordAuthentication no
KbdInteractiveAuthentication no
UsePAM no
AllowUsers root
AllowTcpForwarding local
PermitOpen 127.0.0.1:{exit_port}
LogLevel ERROR
""")
        body = "nodekit-return-traffic-" * 8192
        caddyfile = root / "Caddyfile"
        caddyfile.write_text(f"""{{
 admin off
 auto_https disable_redirects
}}
https://localhost:{https_port}, https://127.0.0.1:{https_port} {{
 bind 127.0.0.1
 tls {cert} {key}
 handle /xhttp-test/* {{
  reverse_proxy h2c://127.0.0.1:{ingress_port} {{
   flush_interval -1
  }}
 }}
 handle {{
  respond "{body}" 200
 }}
}}
""")
        keys = run([str(args.xray), "x25519"])
        private = re.search(r"PrivateKey:\s*(\S+)", keys)[1]
        public = re.search(r"(?:Password \(PublicKey\)|PublicKey):\s*(\S+)", keys)[1]
        exit_uuid, phone_uuid = str(uuid.uuid4()), str(uuid.uuid4())
        exit_stream = {
            "network": "tcp",
            "security": "reality",
            "realitySettings": {
                "target": f"127.0.0.1:{https_port}",
                "serverNames": ["localhost"],
                "privateKey": private,
                "shortIds": ["aabbccdd"],
            },
        }
        exit_config = {
            "log": {"loglevel": "error"},
            "inbounds": [
                {
                    "listen": "127.0.0.1",
                    "port": exit_port,
                    "protocol": "vless",
                    "settings": {
                        "clients": [{"id": exit_uuid, "flow": "xtls-rprx-vision"}],
                        "decryption": "none",
                    },
                    "streamSettings": exit_stream,
                }
            ],
            "outbounds": [
                {
                    "protocol": "freedom",
                    "settings": {
                        "finalRules": [
                            {
                                "action": "allow",
                                "ip": ["127.0.0.1/32"],
                                "network": "tcp",
                                "port": str(https_port),
                            }
                        ]
                    },
                }
            ],
        }
        exit_file = root / "exit.json"
        exit_file.write_text(json.dumps(exit_config))
        node = Node.model_validate(
            {
                "id": "smoke",
                "name": "Smoke",
                "ssh": {"host": "127.0.0.1"},
                "panel": {"port": web_port},
                "caddy": {"enabled": False},
                "deployment": {"panel_runtime": "native", "caddy_mode": "none"},
                "tunnels": [
                    {
                        "name": "exit",
                        "host": "127.0.0.1",
                        "user": "root",
                        "ssh_port": ssh_port,
                        "local_port": forward_port,
                        "target_port": exit_port,
                        "identity_file": str(identity),
                        "known_hosts_file": str(known),
                    }
                ],
            }
        )
        settings = Settings()
        context = AgentContext(
            {
                "node": node.export_config(),
                "action": "tunnel",
                "files": NodeArtifacts(settings.deployment, settings.ssh, YamlCodec()).artifacts(
                    node
                ),
                "runtime": {
                    "deployment": {
                        **settings.deployment.model_dump(),
                        "remote_root": folder,
                        "unit_directory": str(base / "units"),
                        "readiness_interval": 0.1,
                        "probe_timeout": 8,
                    },
                    "limits": settings.limits.model_dump(),
                },
            }
        )
        host = HostEnvironment(context)
        env = {
            **os.environ,
            "XUI_DB_FOLDER": str(base / "db"),
            "XUI_BIN_FOLDER": str(base / "runtime/bin"),
            "XUI_LOG_FOLDER": str(base / "logs"),
            "XUI_ENABLE_FAIL2BAN": "false",
        }
        run(
            [
                str(args.panel),
                "setting",
                "-listenIP",
                "127.0.0.1",
                "-port",
                str(web_port),
                "-webBasePath",
                "/nodekit/",
            ],
            env,
        )
        token_output = run(
            [
                str(args.panel),
                "setting",
                "-getApiToken",
                "-tokenName",
                "smoke",
                "-tokenScope",
                "admin",
            ],
            env,
        )
        token = re.search(r"^apiToken:\s*(\S+)", token_output, re.MULTILINE)[1]
        (base / "api-token").write_text(token)
        (base / "manifest.json").write_text(json.dumps({"node": node.export_config()}))
        forward = ssh_fixture = None
        enabled = False
        command, status = context.command, context.status

        def system_command(values, **kwargs):
            nonlocal forward, enabled
            if args.ssh_backend == "paramiko" and values[:5] == [
                "runuser",
                "-u",
                "root",
                "--",
                "test",
            ]:
                if not os.access(values[-1], os.R_OK):
                    raise OSError()
                return ""
            if values[0] != "systemctl":
                return command(values, **kwargs)
            if values[1] == "show":
                return ""
            if values[1] == "enable" and (forward is None or forward.poll() is not None):
                enabled = True
                text = context.payload["files"][context.unit("exit")]
                exec_line = next(
                    line.split("=", 1)[1]
                    for line in text.splitlines()
                    if line.startswith("ExecStart=")
                )
                forward = start(shlex.split(exec_line), "forward")
            if values[1] == "stop":
                stop(forward)
            if values[1] == "disable":
                enabled = False
            return ""

        def system_status(values):
            if values[0] != "systemctl":
                return status(values)
            return (
                0
                if (enabled if values[1] == "is-enabled" else forward and forward.poll() is None)
                else 1
            )

        context.command, context.status = system_command, system_status
        inspector = SimpleNamespace(
            selected={
                "installation": "managed",
                "active": True,
                "settings": {
                    "webPort": str(web_port),
                    "webBasePath": "/nodekit/",
                    "webCertFile": "",
                },
            },
            database=lambda: base / "db/x-ui.db",
        )
        api = PanelAPI(context, token)
        try:
            start(
                [str(args.caddy), "run", "--config", str(caddyfile)],
                "caddy",
                {
                    **os.environ,
                    "XDG_DATA_HOME": str(root / "caddy-data"),
                    "XDG_CONFIG_HOME": str(root / "caddy-config"),
                },
            )
            start([str(args.xray), "run", "-config", str(exit_file)], "exit")
            if args.ssh_backend == "paramiko":
                from ssh_server import SSHFixture

                ssh_fixture = SSHFixture(
                    hostkey, identity.with_suffix(".pub"), ssh_port, ("127.0.0.1", exit_port)
                )
            else:
                start([str(args.sshd), "-D", "-e", "-f", str(ssh_config)], "sshd")
            start([str(args.panel)], "panel", env)
            for value in (https_port, exit_port, ssh_port, web_port):
                wait(lambda: host.port_open(value))
            direct_result = run(
                [
                    "curl",
                    "--noproxy",
                    "*",
                    "--cacert",
                    str(cert),
                    "--max-time",
                    "5",
                    "-sS",
                    "-o",
                    "/dev/null",
                    "-w",
                    "%{http_code}|%{size_download}",
                    f"https://127.0.0.1:{https_port}/",
                ]
            )
            assert direct_result == f"200|{len(body)}", direct_result
            inbound = api.request(
                "inbounds/add",
                {
                    "remark": "fixture-xhttp",
                    "enable": True,
                    "listen": "127.0.0.1",
                    "port": ingress_port,
                    "protocol": "vless",
                    "settings": json.dumps(
                        {
                            "clients": [
                                {"id": phone_uuid, "email": "fixture-phone", "enable": True}
                            ],
                            "decryption": "none",
                        }
                    ),
                    "streamSettings": json.dumps(
                        {
                            "network": "xhttp",
                            "security": "none",
                            "xhttpSettings": {"path": "/xhttp-test/", "mode": "auto"},
                        }
                    ),
                    "sniffing": "{}",
                    "allocate": "{}",
                },
            )
            inbound = api.request(f"inbounds/get/{inbound['id']}")
            source = {
                "tag": "fixture-exit",
                "protocol": "vless",
                "settings": {
                    "vnext": [
                        {
                            "address": "127.0.0.1",
                            "port": exit_port,
                            "users": [
                                {"id": exit_uuid, "encryption": "none", "flow": "xtls-rprx-vision"}
                            ],
                        }
                    ]
                },
                "streamSettings": {
                    "network": "tcp",
                    "security": "reality",
                    "realitySettings": {
                        "serverName": "localhost",
                        "fingerprint": "chrome",
                        "publicKey": public,
                        "shortId": "aabbccdd",
                    },
                },
            }
            config = TunnelManager.template(api)
            config["outbounds"].append(source)
            # Only this isolated fixture targets a loopback HTTPS server.
            config["routing"]["rules"] = [
                rule
                for rule in config["routing"]["rules"]
                if "geoip:private" not in rule.get("ip", [])
            ]
            api.request("xray/update", {"xraySetting": json.dumps(config)}, form=True)
            context.payload["options"] = {
                "tunnel": {
                    "name": "exit",
                    "outbound_tag": "fixture-exit",
                    "id": inbound["id"],
                    "expected_fingerprint": public_inbound(inbound)["fingerprint"],
                }
            }
            manager = TunnelManager(context, host, PanelDatabase(context), inspector)
            real_probe = manager.probe
            os.environ["CURL_CA_BUNDLE"] = str(cert)
            manager.probe = lambda outbound: real_probe(
                outbound, f"https://127.0.0.1:{https_port}/"
            )
            manager.apply(base)
            manager.apply(base)
            applied = TunnelManager.template(api)
            assert source in applied["outbounds"]
            assert applied["outbounds"][0] == config["outbounds"][0]
            # Real phone-side XHTTP/TLS connection through the resulting Moscow route.
            phone = {
                "log": {"loglevel": "error"},
                "inbounds": [
                    {
                        "listen": "127.0.0.1",
                        "port": socks_port,
                        "protocol": "socks",
                        "settings": {"auth": "noauth", "udp": False},
                    }
                ],
                "outbounds": [
                    {
                        "protocol": "vless",
                        "settings": {
                            "vnext": [
                                {
                                    "address": "127.0.0.1",
                                    "port": https_port,
                                    "users": [{"id": phone_uuid, "encryption": "none"}],
                                }
                            ]
                        },
                        "streamSettings": {
                            "network": "xhttp",
                            "security": "tls",
                            "xhttpSettings": {"path": "/xhttp-test/", "mode": "auto"},
                            "tlsSettings": {
                                "serverName": "localhost",
                                "alpn": ["h2"],
                                "certificates": [{"usage": "verify", "certificateFile": str(cert)}],
                            },
                        },
                    }
                ],
            }
            phone_file = root / "phone.json"
            phone_file.write_text(json.dumps(phone))
            start([str(args.xray), "run", "-config", str(phone_file)], "phone")
            wait(lambda: host.port_open(socks_port))
            result = run(
                [
                    "curl",
                    "--noproxy",
                    "",
                    "--proxy",
                    f"socks5h://127.0.0.1:{socks_port}",
                    "--cacert",
                    str(cert),
                    "--max-time",
                    "10",
                    "-sS",
                    "-o",
                    "/dev/null",
                    "-w",
                    "%{http_code}|%{size_download}",
                    f"https://127.0.0.1:{https_port}/",
                ]
            )
            assert result == f"200|{len(body)}", result
            print(
                json.dumps(
                    {
                        "chain": "XHTTP/TLS -> Caddy -> Moscow 3x-ui -> SSH -> exit VLESS/REALITY -> HTTPS",
                        "http": 200,
                        "bytes": len(body),
                        "identities_preserved": True,
                        "systemctl": "simulated; real generated SSH ExecStart used",
                        "live_VPS_modified": False,
                        "ssh_server": args.ssh_backend,
                    }
                )
            )
        finally:
            if ssh_fixture:
                ssh_fixture.close()
            for process in reversed(jobs):
                stop(process)
            for file in handles:
                file.close()


if __name__ == "__main__":
    main()

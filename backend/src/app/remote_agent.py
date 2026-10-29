"""Standard-library agent sent over SSH stdin. Never installed as a remote daemon."""

import base64
import json
import os
import secrets
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path


def emit(message, level="info"):
    print(json.dumps({"message": message, "level": level}), flush=True)


def run(args, timeout=120):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{args[0]} timed out after {timeout}s") from exc
    if result.returncode:
        # Do not echo command arguments (credentials) or arbitrary container logs.
        detail = "credential setup failed" if "-password" in args else result.stderr[-1500:]
        raise RuntimeError(f"{args[0]} failed ({result.returncode}): {detail}")
    return result.stdout.strip()


def validate_db(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("SQLite integrity check failed")
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"settings", "inbounds", "users"} <= tables:
            raise RuntimeError("Expected a 3x-ui SQLite database (settings, inbounds, users)")
        columns = {r[1] for r in db.execute("PRAGMA table_info(settings)")}
        if not {"key", "value"} <= columns:
            raise RuntimeError("Unsupported settings schema")


def patch_listeners(path, node, restoring):
    panel = node["panel"]
    changes = {
        "webListen": "127.0.0.1",
        "webPort": str(panel["port"]),
        "webCertFile": "",
        "webKeyFile": "",
        "webDomain": "",
        "subListen": "127.0.0.1",
        "subPort": str(panel["subscription_port"]),
        "subCertFile": "",
        "subKeyFile": "",
        "subDomain": "",
    }
    # Keep existing panel paths, subscription IDs/paths, clients and Xray settings on restore.
    if not restoring:
        changes.update(
            webBasePath=panel["base_path"], subPath=panel["subscription_path"], subEnable="true"
        )
    with closing(sqlite3.connect(path)) as db, db:
        if restoring:
            current = dict(db.execute("SELECT key,value FROM settings"))
            expected = current.get("subPath", "/sub/")
            if expected != panel["subscription_path"]:
                raise RuntimeError(
                    "YAML subscription_path must match the backup; refusing URL changes"
                )
            actual = current.get("webBasePath", "/")
            if actual != panel["base_path"]:
                raise RuntimeError("YAML base_path must match the backup; refusing URL changes")
        if node["caddy"]["enabled"]:
            caddy = node["caddy"]
            changes["subURI"] = (
                f"https://{caddy['domain']}:{caddy['https_port']}{panel['subscription_path']}"
            )
        for key, value in changes.items():
            cursor = db.execute("UPDATE settings SET value=? WHERE key=?", (value, key))
            if not cursor.rowcount:
                db.execute("INSERT INTO settings (key,value) VALUES (?,?)", (key, value))


def port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            return True
    except OSError:
        return False


def require_free(port):
    with socket.socket() as sock:
        try:
            sock.bind(("0.0.0.0", port))
        except OSError as exc:
            raise RuntimeError(
                f"Port {port} already occupied; existing services will not be stopped"
            ) from exc


def environment():
    if os.geteuid() != 0:
        raise RuntimeError("Use root or ssh.sudo: true with non-interactive sudo")
    if not Path("/run/systemd/system").exists():
        raise RuntimeError("Target must be a Linux VPS running systemd")
    for executable in ("docker", "ssh", "systemctl"):
        if not shutil.which(executable):
            raise RuntimeError(f"Missing prerequisite: {executable}")
    run(["docker", "info", "--format", "{{.ServerVersion}}"])
    run(["docker", "compose", "version"])
    emit("Docker daemon, Compose, OpenSSH and systemd available")


def snapshot(source, destination):
    with closing(sqlite3.connect(Path(source).resolve().as_uri() + "?mode=ro", uri=True)) as src:
        with closing(sqlite3.connect(destination)) as dst, dst:
            src.backup(dst)
    validate_db(destination)
    os.chmod(destination, 0o600)


def doctor(node, base):
    failures = []
    panel = node["panel"]
    url = f"http://127.0.0.1:{panel['port']}{panel['base_path']}"
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=8) as response:
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status}")
        emit("Panel HTTP: OK")
    except (OSError, urllib.error.URLError, RuntimeError) as exc:
        failures.append(f"Panel HTTP: {exc}")
    if port_open(panel["subscription_port"]):
        emit("Subscription backend TCP: OK (a real client subscription is not tested)")
    else:
        failures.append("Subscription backend TCP: unavailable")
    for tunnel in node["tunnels"]:
        unit = f"omsi-{node['id']}-{tunnel['name']}.service"
        state = subprocess.run(["systemctl", "is-active", "--quiet", unit], check=False).returncode
        if state or not port_open(tunnel["local_port"]):
            failures.append(f"Tunnel {tunnel['name']}: unavailable")
        else:
            emit(f"Tunnel {tunnel['name']}: process/listener OK; data path not verified")
    if node.get("probe"):
        if not shutil.which("curl"):
            failures.append("End-to-end probe requires curl on the VPS")
        else:
            probe = node["probe"]
            try:
                run(
                    [
                        "curl",
                        "--noproxy",
                        "",
                        "--fail",
                        "--silent",
                        "--show-error",
                        "--max-time",
                        "20",
                        "--proxy",
                        f"socks5h://127.0.0.1:{probe['socks_port']}",
                        probe["url"],
                    ],
                    timeout=25,
                )
                emit("HTTPS request through configured SOCKS outbound: OK")
            except RuntimeError as exc:
                failures.append(f"End-to-end probe: {exc}")
    else:
        emit("End-to-end proxy probe: NOT CONFIGURED", "warning")
    if node["caddy"]["enabled"]:
        emit(
            "Public DNS, ACME certificate and client-side connectivity require an external check",
            "warning",
        )
    for failure in failures:
        emit(failure, "error")
    if failures:
        raise RuntimeError(f"Diagnostics found {len(failures)} failure(s)")


def deploy(payload, base):
    import pwd

    node, action = payload["node"], payload["action"]
    if base.exists() and any(base.iterdir()):
        raise RuntimeError(
            "Target directory is not empty. Fresh/restore only target new nodes; existing data is preserved"
        )
    if (
        subprocess.run(
            ["systemctl", "is-active", "--quiet", "x-ui"], capture_output=True, check=False
        ).returncode
        == 0
    ):
        raise RuntimeError("Native x-ui is running; migrate manually to a new VPS")
    existing = run(
        ["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project=omsi-{node['id']}"]
    )
    if existing:
        raise RuntimeError(
            "Docker Compose project already exists; refusing to replace its containers"
        )
    ports = [node["panel"]["port"], node["panel"]["subscription_port"]]
    ports += [t["local_port"] for t in node["tunnels"]]
    if node["caddy"]["enabled"]:
        ports += [80, node["caddy"]["https_port"]]
    for port in ports:
        require_free(port)
    for tunnel in node["tunnels"]:
        pwd.getpwnam(tunnel["user"])
        for key in ("identity_file", "known_hosts_file"):
            run(["runuser", "-u", tunnel["user"], "--", "test", "-r", tunnel[key]])
    if action == "restore":
        raw = base64.b64decode(payload["backup"], validate=True)
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            tmp.write(raw)
            tmp.flush()
            validate_db(tmp.name)
    emit("Preflight complete; no existing installation is being replaced")
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    base.chmod(0o700)
    for folder in ("db", "cert", "caddy-data", "caddy-config"):
        (base / folder).mkdir(mode=0o700)
    for name, content in payload["files"].items():
        (base / name).write_text(content)
        (base / name).chmod(0o600)
    compose = ["docker", "compose", "-f", str(base / "compose.yaml")]
    started_units = []
    try:
        run(compose + ["config", "--quiet"])
        emit("Pulling pinned images (this can take several minutes)")
        run(compose + ["pull"], timeout=600)
        db_path = base / "db" / "x-ui.db"
        if action == "restore":
            db_path.write_bytes(raw)
            emit("SQLite backup restored; client identities preserved")
        else:
            password = secrets.token_urlsafe(28)
            run(
                compose
                + [
                    "run",
                    "--rm",
                    "--no-deps",
                    "--entrypoint",
                    "/app/x-ui",
                    "panel",
                    "setting",
                    "-username",
                    "omsi",
                    "-password",
                    password,
                    "-port",
                    str(node["panel"]["port"]),
                    "-listenIP",
                    "127.0.0.1",
                    "-webBasePath",
                    node["panel"]["base_path"],
                ]
            )
            credentials = base / "credentials.json"
            credentials.write_text(json.dumps({"username": "omsi", "password": password}))
            credentials.chmod(0o600)
            emit(f"Fresh credentials saved on VPS: {credentials} (not copied to logs)")
        validate_db(db_path)
        patch_listeners(db_path, node, action == "restore")
        db_path.chmod(0o600)
        # Copy only units belonging to this new node; refuse pre-existing names.
        for name, content in payload["files"].items():
            if name.endswith(".service"):
                target = Path("/etc/systemd/system") / name
                if target.exists():
                    raise RuntimeError(f"Unit already exists: {name}")
                target.write_text(content)
                target.chmod(0o644)
                started_units.append(name)
        if started_units:
            run(["systemctl", "daemon-reload"])
            run(["systemctl", "enable", "--now", *started_units])
        if node["caddy"]["enabled"]:
            run(
                compose
                + [
                    "run",
                    "--rm",
                    "--no-deps",
                    "caddy",
                    "caddy",
                    "validate",
                    "--config",
                    "/etc/caddy/Caddyfile",
                ]
            )
        run(compose + ["up", "-d"], timeout=180)
        emit("Services started; waiting for panel HTTP")
        for _ in range(30):
            if port_open(node["panel"]["port"]):
                break
            time.sleep(1)
        doctor(node, base)
        (base / "manifest.json").write_text(json.dumps({"node": node, "action": action}, indent=2))
        emit("Deployment complete. Inbounds/outbounds come from the backup; fresh panels are empty")
    except Exception:
        emit(
            "Deployment failed; stopping this node's services. Files are retained for inspection",
            "error",
        )
        subprocess.run(compose + ["stop"], capture_output=True, timeout=60, check=False)
        if started_units:
            subprocess.run(
                ["systemctl", "disable", "--now", *started_units],
                capture_output=True,
                timeout=30,
                check=False,
            )
        raise


def main(payload):
    import fcntl

    os.umask(0o077)
    environment()
    node, action = payload["node"], payload["action"]
    base = Path(f"/opt/omsi-nodekit/{node['id']}")
    # A VPS-wide lock also protects different local Nodekit instances / node IDs.
    with open("/run/lock/omsi-nodekit.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Another Nodekit operation is running on this VPS") from exc
        if action in {"fresh", "restore"}:
            deploy(payload, base)
        elif action == "doctor":
            doctor(node, base)
        elif action == "backup":
            source = base / "db" / "x-ui.db"
            if not source.is_file():
                raise RuntimeError("No managed database found; refusing an empty backup")
            with tempfile.TemporaryDirectory() as tmp:
                destination = Path(tmp) / "x-ui.db"
                snapshot(source, destination)
                if destination.stat().st_size > 64 * 1024 * 1024:
                    raise RuntimeError("Database exceeds the 64 MiB MVP limit")
                # Data is a machine event, never appended to user-visible job logs.
                print(
                    json.dumps({"backup": base64.b64encode(destination.read_bytes()).decode()}),
                    flush=True,
                )
            emit(
                "Consistent SQLite snapshot downloaded; external certificates and SSH keys are separate"
            )
        elif action == "check":
            emit("SSH/environment check complete; no changes made")
        else:
            raise RuntimeError("Unknown action")

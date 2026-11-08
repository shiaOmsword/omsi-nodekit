"""Create a consistent, private wg-easy v15 SQLite snapshot on its Docker host."""

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path


class ExportError(ValueError):
    pass


def docker(*args):
    result = subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=False, timeout=30
    )
    if result.returncode:
        raise ExportError("Docker inspection failed; check the container name and privileges")
    return result.stdout


def export(container, destination):
    info = json.loads(docker("inspect", container))[0]
    if not info["State"]["Running"]:
        raise ExportError("wg-easy must be running so its actual runtime can be inspected")
    env = dict(value.split("=", 1) for value in info["Config"].get("Env", []) if "=" in value)
    interface = env.get("WG_INTERFACE") or "wg0"
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,15}", interface):
        raise ExportError("Unsupported WireGuard interface name")
    config = docker("exec", container, "cat", f"/etc/wireguard/{interface}.conf")
    if re.search(r"^\s*(?:Jc|Jmin|Jmax|S[1-4]|H[1-4]|I[1-5])\s*=", config, re.M | re.I):
        raise ExportError(
            "The running interface uses AmneziaWG; this importer accepts ordinary WireGuard"
        )
    mounts = [m for m in info["Mounts"] if m["Destination"] == "/etc/wireguard"]
    if len(mounts) != 1:
        raise ExportError("Cannot locate the /etc/wireguard Docker mount")
    source = Path(mounts[0]["Source"]) / "wg-easy.db"
    if not source.is_file() or source.is_symlink():
        raise ExportError("Cannot locate the wg-easy v15 SQLite database")
    source_ipv6 = env.get("DISABLE_IPV6") != "true"
    address_line = re.search(r"^Address\s*=\s*(.+)$", config, re.M)
    if not address_line or (":" in address_line[1]) != source_ipv6:
        raise ExportError(
            "Runtime configuration and DISABLE_IPV6 disagree; refresh wg-easy before exporting"
        )
    destination = Path(destination).absolute()
    if destination.resolve() == source.resolve():
        raise ExportError("The snapshot destination must differ from the live database")
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    try:
        with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as live:
            with closing(sqlite3.connect(destination)) as snapshot:
                live.backup(snapshot)
                if snapshot.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise ExportError("SQLite snapshot integrity check failed")
                tables = {
                    r[0]
                    for r in snapshot.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                if (
                    not {"interfaces_table", "clients_table", "user_configs_table", "hooks_table"}
                    <= tables
                ):
                    raise ExportError("The database does not have the expected wg-easy v15 schema")
        os.chmod(destination, 0o600)
        if (
            getattr(os, "geteuid", lambda: -1)() == 0
            and os.environ.get("SUDO_UID")
            and os.environ.get("SUDO_GID")
        ):
            os.chown(destination, int(os.environ["SUDO_UID"]), int(os.environ["SUDO_GID"]))
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return {
        "snapshot": str(destination),
        "image": info["Config"]["Image"],
        "source_ipv6": source_ipv6,
        "protocol": "wireguard",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", default="wg-easy")
    parser.add_argument(
        "--output", required=True, help="New .db file; existing files are never overwritten"
    )
    args = parser.parse_args()
    try:
        print(json.dumps(export(args.container, args.output), ensure_ascii=False, indent=2))
    except ExportError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, ValueError, sqlite3.Error, subprocess.SubprocessError, KeyError, IndexError):
        print(
            "Export failed. Check Docker access, ordinary WireGuard runtime, v15 schema, DISABLE_IPV6 and a new writable destination. No keys were printed.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

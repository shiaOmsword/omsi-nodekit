#!/usr/bin/env python3
"""Read-only audit of a 3x-ui SQLite backup and Nodekit recovery sidecars.

Never prints credentials, raw database values, or private configuration.
This script neither deletes nor restarts anything.
"""

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

MAX_ROWS = 100000
SIDECARS = (
    "manifest.json", "compose.yaml", "Caddyfile.site",
    "inbound-identities.json", "firewall-rules.json",
    "xhttp-routes.json", "subscriptions.json", "api-token",
)


def open_readonly(path):
    if not path.is_file():
        raise ValueError("SQLite file does not exist")
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def summary(path):
    with open_readonly(path) as db:
        db.execute("PRAGMA query_only=ON")
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError("SQLite integrity_check failed")
        if db.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("SQLite foreign_key_check failed")
        tables = [
            row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        counts = {}
        fingerprints = {}
        for table in tables:
            safe_name = '"' + table.replace('"', '""') + '"'
            count = db.execute(f"SELECT COUNT(*) FROM {safe_name}").fetchone()[0]
            if count > MAX_ROWS:
                raise ValueError("Table is larger than read-only audit limit")
            counts[table] = count
            hashes = [
                hashlib.sha256(repr(tuple(row)).encode("utf-8")).digest()
                for row in db.execute(f"SELECT * FROM {safe_name}")
            ]
            digest = hashlib.sha256()
            for value in sorted(hashes):
                digest.update(value)
            fingerprints[table] = digest.digest()
        return counts, fingerprints


def audit(live, backup, root):
    original_counts, original_digest = summary(live)
    copy_counts, copy_digest = summary(backup)
    tables = sorted(set(original_counts) | set(copy_counts))
    sidecars = {
        name: (root / name).is_file() and not (root / name).is_symlink()
        for name in SIDECARS
    }
    tunnels = sorted(p.name for p in root.glob("tunnel-*.json") if p.is_file() and not p.is_symlink())
    pools = sorted(p.name for p in root.glob("pool-*.json") if p.is_file() and not p.is_symlink())
    return {
        "integrity": "ok",
        "same_schema_tables": set(original_counts) == set(copy_counts),
        "tables": {
            table: {
                "source_rows": original_counts.get(table),
                "backup_rows": copy_counts.get(table),
                "identical_rows": original_digest.get(table) == copy_digest.get(table),
            } for table in tables
        },
        "all_rows_identical": (
            original_counts == copy_counts
            and all(original_digest.get(t) == copy_digest.get(t) for t in tables)
        ),
        "recovery_files_present": sidecars,
        "ssh_tunnel_state_files": tunnels,
        "ssh_pool_state_files": pools,
        "note": (
            "SQLite alone does not include SSH systemd units, SSH private keys, "
            "shared Caddy config, UFW changes, Nodekit metadata or external TLS assets."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", required=True, type=Path, help="current 3x-ui x-ui.db")
    parser.add_argument("--backup", required=True, type=Path, help="backup .db")
    parser.add_argument("--root", required=True, type=Path, help="Nodekit managed directory")
    args = parser.parse_args()
    try:
        report = audit(args.live, args.backup, args.root)
    except (OSError, ValueError, sqlite3.DatabaseError) as error:
        print(json.dumps({"status": "failed", "reason": type(error).__name__}))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["all_rows_identical"] else 1


if __name__ == "__main__":
    sys.exit(main())

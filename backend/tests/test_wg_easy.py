import base64
import copy
import importlib.util
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from fastapi.testclient import TestClient

from app.agent.context import AgentContext
from app.agent.wireguard import WireGuardManager
from app.backup_wireguard import public_catalog, read_wireguard, select_wireguard
from app.create_app import create_app
from app.services.backups import BackupService
from app.wg_easy import read_wg_easy
from framework.database import SQLiteSnapshots
from framework.entities import ValidationError


def key(value):
    return base64.b64encode(bytes([value]) * 32).decode()


def public_key(value):
    return base64.b64encode(
        X25519PrivateKey.from_private_bytes(bytes([value]) * 32).public_key().public_bytes_raw()
    ).decode()


@pytest.fixture
def wg_db(tmp_path):
    path = tmp_path / "wg-easy.db"
    # The v15 SQLite table and column names, independent of the import model.
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE interfaces_table (
                name TEXT PRIMARY KEY, device TEXT, port INTEGER, private_key TEXT,
                public_key TEXT, ipv4_cidr TEXT, ipv6_cidr TEXT, mtu INTEGER,
                enabled INTEGER, routing_table TEXT, firewall_enabled INTEGER
            );
            CREATE TABLE user_configs_table (
                id TEXT PRIMARY KEY, default_mtu INTEGER, default_persistent_keepalive INTEGER,
                default_dns TEXT, default_allowed_ips TEXT, host TEXT, port INTEGER
            );
            CREATE TABLE hooks_table (
                id TEXT PRIMARY KEY, pre_up TEXT, post_up TEXT, pre_down TEXT, post_down TEXT
            );
            CREATE TABLE clients_table (
                id INTEGER PRIMARY KEY, interface_id TEXT, name TEXT, ipv4_address TEXT,
                ipv6_address TEXT, private_key TEXT, public_key TEXT, pre_shared_key TEXT,
                expires_at TEXT, allowed_ips TEXT, server_allowed_ips TEXT,
                persistent_keepalive INTEGER, mtu INTEGER, dns TEXT, server_endpoint TEXT,
                enabled INTEGER, pre_up TEXT, post_up TEXT, pre_down TEXT, post_down TEXT
            );
        """)
        db.execute(
            "INSERT INTO interfaces_table VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "wg0",
                "eth0",
                51820,
                key(1),
                public_key(1),
                "10.8.0.0/24",
                "fd00:8::/64",
                1420,
                1,
                "auto",
                0,
            ),
        )
        db.execute(
            "INSERT INTO user_configs_table VALUES (?,?,?,?,?,?,?)",
            (
                "wg0",
                1420,
                0,
                '["1.1.1.1"]',
                '["0.0.0.0/0","::/0"]',
                "198.51.100.10",
                51820,
            ),
        )
        db.execute("INSERT INTO hooks_table VALUES ('wg0','','','','')")
        for identifier, name, enabled, end, keepalive in (
            (1, "alpha", 1, "2027-01-30T12:00:00+03:00", 25),
            (2, "Телефон Александра", 0, None, 0),
        ):
            db.execute(
                "INSERT INTO clients_table VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    identifier,
                    "wg0",
                    name,
                    f"10.8.0.{identifier + 1}",
                    f"fd00:8::{identifier + 1}",
                    key(identifier + 3),
                    public_key(identifier + 3),
                    key(identifier + 9),
                    end,
                    None,
                    "[]",
                    keepalive,
                    1420,
                    None,
                    None,
                    enabled,
                    "",
                    "",
                    "",
                    "",
                ),
            )
    return path


def update(path, table, column, value, where="id=1"):
    with sqlite3.connect(path) as db:
        db.execute(f"UPDATE {table} SET {column}=? WHERE {where}", (value,))


def test_preserves_identities_policies_names_and_source_bytes(wg_db):
    original = wg_db.read_bytes()
    source = select_wireguard(wg_db, 1, source_ipv6=True)
    assert source["settings"]["secretKey"] == key(1)
    assert source["settings"]["subnetIp"] == "10.8.0.0"
    assert source["settings"]["subnetCidr"] == 24
    assert source["settings"]["mtu"] == 1420
    assert source["settings"]["dns"] == "1.1.1.1"
    first, second = source["clients"]
    assert (first["privateKey"], first["publicKey"], first["preSharedKey"]) == (
        key(4),
        public_key(4),
        key(10),
    )
    assert first["allowedIPs"] == ["10.8.0.2/32", "fd00:8::2/128"]
    assert first["keepAlive"] == 25 and first["enable"] is True
    assert first["expiryTime"] == int(
        datetime(2027, 1, 30, 9, tzinfo=timezone.utc).timestamp() * 1000
    )
    assert second["comment"] == "Телефон Александра"
    assert second["email"] == "wg-easy-wg0-2"
    assert second["keepAlive"] == 0 and second["enable"] is False
    assert second["expiryTime"] == 0
    assert wg_db.read_bytes() == original
    assert "subId" not in first  # Assigned by 3x-ui import, never confused with WG identities.


def test_runtime_ipv6_choice_is_required_and_not_inferred_from_stored_addresses(wg_db):
    with pytest.raises(ValueError, match="DISABLE_IPV6"):
        select_wireguard(wg_db, 1)
    source = select_wireguard(wg_db, 1, source_ipv6=False)
    assert source["clients"][0]["allowedIPs"] == ["10.8.0.2/32"]
    with pytest.raises(ValueError):
        select_wireguard(wg_db, 1, source_ipv6="false")


def test_public_catalog_never_exposes_private_material(wg_db, container):
    backups = container.resolve(BackupService)
    backup = backups.import_backup(wg_db.read_bytes(), "wg-easy.db")
    catalog = backups.wireguard(backup.id)
    assert catalog[0]["source_format"] == "wg-easy-v15"
    assert catalog[0]["client_count"] == 2
    assert catalog[0]["endpoint"] == {"host": "198.51.100.10", "port": 51820}
    assert catalog[0]["blockers"] == []
    serialized = json.dumps(catalog)
    for secret in (key(1), key(4), key(5), key(10), key(11)):
        assert secret not in serialized
    assert backups.content(backup.id) == wg_db.read_bytes()
    with pytest.raises(ValidationError):
        backups.restore_profile(backup.id)
    with pytest.raises(ValidationError):
        backups.clients(backup.id)


@pytest.mark.parametrize(
    "table,column,value,where,blocker",
    [
        ("clients_table", "dns", '["8.8.8.8"]', "id=1", "client_dns"),
        ("clients_table", "mtu", 1280, "id=1", "client_mtu"),
        ("clients_table", "allowed_ips", '["192.0.2.0/24"]', "id=1", "client_routes"),
        ("clients_table", "server_allowed_ips", '["192.0.2.0/24"]', "id=1", "server_routes"),
        ("clients_table", "server_endpoint", "192.0.2.10:51820", "id=1", "server_endpoint"),
        ("clients_table", "post_up", "custom-command --secret value", "id=1", "client_hooks"),
        ("hooks_table", "post_up", "custom-command --secret value", "id='wg0'", "server_hooks"),
        ("interfaces_table", "firewall_enabled", 1, "name='wg0'", "firewall"),
        ("interfaces_table", "routing_table", "123", "name='wg0'", "routing_table"),
        ("user_configs_table", "default_dns", '["10.8.0.1"]', "id='wg0'", "gateway_dns"),
    ],
)
def test_incompatible_settings_are_reported_and_block_import(
    wg_db, table, column, value, where, blocker
):
    update(wg_db, table, column, value, where)
    catalog = public_catalog(read_wireguard(wg_db))
    assert blocker in catalog[0]["blockers"]
    assert "custom-command" not in json.dumps(catalog)
    with pytest.raises(ValueError, match=blocker):
        select_wireguard(wg_db, 1, source_ipv6=False)


@pytest.mark.parametrize(
    "column,value",
    [
        ("public_key", "do-not-leak-invalid-key"),
        ("dns", "do-not-leak-invalid-json"),
        ("persistent_keepalive", -1),
        ("enabled", 2),
        ("ipv4_address", "10.8.0.3"),
        ("ipv4_address", "10.8.0.1"),
        ("expires_at", "do-not-leak-invalid-date"),
    ],
)
def test_invalid_sources_fail_without_echoing_private_values(wg_db, column, value):
    update(wg_db, "clients_table", column, value)
    with pytest.raises(ValueError) as error:
        read_wg_easy(wg_db)
    assert "do-not-leak" not in str(error.value)


def test_default_nat_hooks_are_recognized_without_executing_them(wg_db):
    for action, field in (("-A", "post_up"), ("-D", "post_down")):
        hooks = f"iptables -t nat {action} POSTROUTING -s {{{{ipv4Cidr}}}} -o {{{{device}}}} -j MASQUERADE; iptables {action} INPUT -p udp -m udp --dport {{{{port}}}} -j ACCEPT; iptables {action} FORWARD -i wg0 -j ACCEPT; iptables {action} FORWARD -o wg0 -j ACCEPT;"
        update(wg_db, "hooks_table", field, hooks, "id='wg0'")
    assert select_wireguard(wg_db, 1, source_ipv6=False)["blockers"] == []


def test_duplicate_and_unsafe_names_have_unique_stable_accounts(wg_db):
    update(wg_db, "clients_table", "name", "ALPHA", "id=2")
    first = read_wg_easy(wg_db)[0]["clients"]
    assert [c["email"] for c in first] == ["wg-easy-wg0-1", "wg-easy-wg0-2"]
    assert [c["comment"] for c in first] == ["alpha", "ALPHA"]


@pytest.mark.parametrize(
    "table,where", [("interfaces_table", "name='wg0'"), ("clients_table", "id=1")]
)
def test_mismatched_private_public_key_pairs_are_rejected(wg_db, container, table, where):
    update(wg_db, table, "public_key", key(123), where)
    with pytest.raises(ValidationError) as error:
        container.resolve(BackupService).import_backup(wg_db.read_bytes(), "wg-easy.db")
    assert key(123) not in str(error.value)


def test_peer_without_private_key_and_without_psk_is_not_regenerated(wg_db, container):
    update(wg_db, "clients_table", "private_key", "")
    update(wg_db, "clients_table", "pre_shared_key", key(0))
    backup = container.resolve(BackupService).import_backup(wg_db.read_bytes(), "wg-easy.db")
    assert (
        container.resolve(BackupService).wireguard(backup.id)[0]["clients"][0]["has_private_key"]
        is False
    )
    peer = select_wireguard(wg_db, 1, source_ipv6=False)["clients"][0]
    assert peer["privateKey"] == peer["preSharedKey"] == ""
    assert peer["publicKey"] == public_key(4)


def exporter():
    spec = importlib.util.spec_from_file_location(
        "export_wg_easy", Path(__file__).parents[2] / "tools/export_wg_easy.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def docker_fixture(wg_db, config="Address = 10.8.0.1/24", disable_ipv6="true"):
    info = [
        {
            "State": {"Running": True},
            "Config": {
                "Image": "ghcr.io/wg-easy/wg-easy:15",
                "Env": [f"DISABLE_IPV6={disable_ipv6}", "PASSWORD=must-not-leak"],
            },
            "Mounts": [{"Source": str(wg_db.parent), "Destination": "/etc/wireguard"}],
        }
    ]
    return lambda *args: json.dumps(info) if args[0] == "inspect" else config


def test_exporter_snapshots_committed_wal_and_keeps_files_private(wg_db, tmp_path, monkeypatch):
    module = exporter()
    monkeypatch.setattr(module, "docker", docker_fixture(wg_db))
    destination = tmp_path / "consistent.db"
    with sqlite3.connect(wg_db) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("UPDATE clients_table SET name='committed-in-wal' WHERE id=1")
        writer.commit()
        result = module.export("wg-easy", destination)
        with sqlite3.connect(destination) as snapshot:
            assert (
                snapshot.execute("SELECT name FROM clients_table WHERE id=1").fetchone()[0]
                == "committed-in-wal"
            )
        with pytest.raises(FileExistsError):
            module.export("wg-easy", destination)
    assert result["source_ipv6"] is False
    assert "must-not-leak" not in json.dumps(result)
    if os.name != "nt":
        assert destination.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "config,disable_ipv6",
    [
        ("Address = 10.8.0.1/24\nJc = 7", "true"),
        ("Address = 10.8.0.1/24", "false"),
    ],
)
def test_exporter_rejects_amnezia_and_inconsistent_runtime(
    wg_db, tmp_path, monkeypatch, config, disable_ipv6
):
    module = exporter()
    monkeypatch.setattr(module, "docker", docker_fixture(wg_db, config, disable_ipv6))
    destination = tmp_path / "refused.db"
    with pytest.raises(module.ExportError):
        module.export("wg-easy", destination)
    assert not destination.exists()


def test_preview_and_launch_validate_source_before_scheduling(
    wg_db, settings, container, node_yaml
):
    with TestClient(
        create_app(settings, container=container),
        base_url="http://127.0.0.1:8765",
        headers={"X-Nodekit-Request": "1"},
    ) as client:
        node = client.put("/api/nodes/test-node", json={"yaml": node_yaml}).json()["data"]
        backup = client.post("/api/backups?filename=wg-easy.db", content=wg_db.read_bytes()).json()[
            "data"
        ]
        request = {
            "action": "wireguard",
            "revision": node["revision"],
            "backup_id": backup["id"],
            "wireguard": {
                "operation": "restore",
                "remark": "migrated",
                "domain": "203.0.113.10",
                "port": 51820,
                "source_inbound_id": 1,
            },
        }
        for endpoint in ("plan", "jobs"):
            response = client.post(f"/api/nodes/test-node/{endpoint}", json=request)
            assert response.status_code == 422
            assert "DISABLE_IPV6" in response.text
        request["wireguard"]["source_ipv6"] = False
        response = client.post("/api/nodes/test-node/plan", json=request)
        assert response.status_code == 200, response.text
        plan = response.json()["data"]
        assert any(
            "198.51.100.10:51820" in step and "203.0.113.10:51820" in step for step in plan["steps"]
        )
        assert key(1) not in response.text
        assert client.get("/api/jobs").json()["data"] == []


def test_remote_import_preserves_source_and_never_generates_new_wg_keys(
    wg_db, node, monkeypatch, tmp_path, settings
):
    proposed = {}
    events = []

    class API:
        def request(self, path, data=None):
            if path == "clients/list":
                return []
            if path == "inbounds/list":
                return []
            if path == "inbounds/add":
                proposed.update(copy.deepcopy(data))
                proposed["settings"] = json.loads(proposed["settings"])
                return {"id": 99}
            if path == "inbounds/get/99":
                return copy.deepcopy(proposed)
            if path == "server/restartXrayService":
                return None
            pytest.fail(f"Unexpected API call: {path}")

    payload = {
        "node": node.export_config(),
        "runtime": {
            "deployment": settings.deployment.model_dump(),
            "limits": settings.limits.model_dump(),
        },
        "backup": base64.b64encode(wg_db.read_bytes()).decode(),
        "options": {
            "wireguard": {
                "operation": "restore",
                "source_inbound_id": 1,
                "source_ipv6": False,
                "remark": "migrated",
                "domain": "203.0.113.10",
                "port": 51820,
                "mtu": 1280,
                "dns": "8.8.8.8",
            }
        },
    }
    payload["node"]["caddy"]["enabled"] = True
    context = AgentContext(payload)
    context.emit = lambda *args: events.append(args)
    inspector = SimpleNamespace(
        selected={"settings": {"subURI": "https://example.test/sub/", "subEnable": "true"}},
        report={},
    )
    monkeypatch.setattr("app.agent.wireguard.public_base", lambda node: "https://example.test/sub/")
    monkeypatch.setattr("app.agent.wireguard.managed_api", lambda *args: API())
    host = SimpleNamespace(udp_port_bound=lambda port: bool(proposed), context=context)
    snapshots = []
    database = SimpleNamespace(snapshot=lambda *args: snapshots.append(args))
    inspector.database = lambda: tmp_path / "target.db"
    context.snapshots = SQLiteSnapshots()
    WireGuardManager(context, host, database, inspector).apply(tmp_path)
    restored = proposed["settings"]
    assert snapshots and restored["secretKey"] == key(1)
    assert restored["mtu"] == 1420 and restored["dns"] == "1.1.1.1"
    assert restored["clients"][0]["privateKey"] == key(4)
    assert restored["clients"][1]["enable"] is False
    assert restored["clients"][1]["comment"] == "Телефон Александра"
    assert all(c["id"] and c["subId"] for c in restored["clients"])
    assert key(1) not in str(events)

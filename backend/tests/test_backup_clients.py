"""SQLite client migrations preserve UUID/subId and never adopt foreign identities."""

import base64
import copy
import json
import sqlite3
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agent.backup_client_import import BackupClientImporter, new_payload
from app.agent.inbound_meta import public_inbound
from app.backup_clients import public_catalog, read_catalog, select_clients
from app.create_app import create_app
from app.entities.job_request import JobRequest
from tests.conftest import create_database
from tests.test_subscriptions import owned as owned


def backup(path, normalized=True):
    create_database(path)
    with sqlite3.connect(path) as db:
        for col, typ in (("remark", "TEXT"), ("protocol", "TEXT")):
            db.execute(f"ALTER TABLE inbounds ADD COLUMN {col} {typ}")
        db.execute(
            "UPDATE inbounds SET remark='legacy',protocol='vless',settings=?",
            (
                json.dumps(
                    {
                        "clients": [
                            {
                                "email": "alpha",
                                "id": "11111111-1111-4111-8111-111111111111",
                                "subId": "keepSubIdAlpha",
                                "flow": "xtls-rprx-vision",
                                "enable": True,
                            },
                            {
                                "email": "beta",
                                "id": "22222222-2222-4222-8222-222222222222",
                                "subId": "keepSubIdBeta",
                                "enable": False,
                            },
                        ]
                    }
                ),
            ),
        )
        if normalized:
            db.executescript("""
                CREATE TABLE clients (
                  id INTEGER PRIMARY KEY, email TEXT, sub_id TEXT, uuid TEXT,
                  flow TEXT, enable INTEGER, expiry_time INTEGER, total_gb INTEGER,
                  limit_ip INTEGER, comment TEXT
                );
                CREATE TABLE client_inbounds (
                  client_id INTEGER, inbound_id INTEGER, flow_override TEXT
                );
            """)
            db.execute(
                "INSERT INTO clients VALUES (3,?,?,?,?,?,?,?,?,?)",
                (
                    "alpha",
                    "keepSubIdAlpha",
                    "33333333-3333-4333-8333-333333333333",
                    "xtls-rprx-vision",
                    1,
                    1770000000000,
                    1048576,
                    1,
                    "from-backup",
                ),
            )
            db.execute(
                "INSERT INTO clients VALUES (4,?,?,?,?,?,?,?,?,?)",
                (
                    "beta",
                    "keepSubIdBeta",
                    "44444444-4444-4444-8444-444444444444",
                    "",
                    0,
                    0,
                    0,
                    0,
                    "inactive",
                ),
            )
            db.execute("INSERT INTO client_inbounds VALUES (3,1,'')")
            db.execute("INSERT INTO client_inbounds VALUES (4,1,'')")
    return path


def test_normalized_client_tables_are_authoritative_and_private(tmp_path):
    path = backup(tmp_path / "x-ui.db")
    catalog = read_catalog(path)
    safe = public_catalog(catalog)
    assert len(catalog) == 1 and len(catalog[0]["clients"]) == 2
    assert safe["inbounds"][0]["clients"][0] == {
        "ref": "n:3",
        "email": "alpha",
        "enabled": True,
        "has_subscription": True,
        "restorable": True,
        "external_link_count": 0,
        "external_links_compatible": True,
        "depends_on": [],
    }
    assert "keepSubIdAlpha" not in json.dumps(safe)
    assert "33333333-3333-4333-8333-333333333333" not in json.dumps(safe)
    selected = select_clients(catalog, 1, ["n:3"])
    assert selected[0]["subId"] == "keepSubIdAlpha"
    assert selected[0]["id"] == "33333333-3333-4333-8333-333333333333"
    assert selected[0]["expiryTime"] == 1770000000000
    assert selected[0]["comment"] == "from-backup"


def test_legacy_backup_clients_are_supported(tmp_path):
    path = backup(tmp_path / "legacy.db", normalized=False)
    catalog = read_catalog(path)
    assert [c["ref"] for c in catalog[0]["clients"]] == ["l:0", "l:1"]
    selected = select_clients(catalog, 1, ["l:1"])
    assert selected[0]["subId"] == "keepSubIdBeta"
    assert selected[0]["enable"] is False


def test_missing_source_subscription_never_generates_new_id(tmp_path):
    path = backup(tmp_path / "invalid.db", normalized=False)
    with sqlite3.connect(path) as db:
        value = json.loads(db.execute("SELECT settings FROM inbounds WHERE id=1").fetchone()[0])
        value["clients"][0].pop("subId")
        db.execute("UPDATE inbounds SET settings=? WHERE id=1", (json.dumps(value),))
    catalog = read_catalog(path)
    assert not catalog[0]["clients"][0]["restorable"]
    with pytest.raises(ValueError):
        select_clients(catalog, 1, ["l:0"])


def test_selected_source_must_be_unambiguous(tmp_path):
    catalog = read_catalog(backup(tmp_path / "source.db"))
    for refs in ([], ["n:3", "n:3"], ["n:404"], ["l:0"]):
        with pytest.raises(ValueError):
            select_clients(catalog, 1, refs)


def test_catalog_endpoint_never_returns_secrets(settings, container, tmp_path):
    path = backup(tmp_path / "source.db")
    with TestClient(
        create_app(settings, container=container),
        base_url=f"http://127.0.0.1:{settings.server.port}",
        headers={"X-Nodekit-Request": "1"},
    ) as client:
        response = client.post("/api/backups?filename=x-ui.db", content=path.read_bytes())
        assert response.status_code == 201
        identifier = response.json()["data"]["id"]
        found = client.get(f"/api/backups/{identifier}/clients")
        assert found.status_code == 200
        data = found.json()["data"]
        assert data["inbounds"][0]["clients"][0]["email"] == "alpha"
        assert "keepSubIdAlpha" not in found.text
        assert "33333333-3333-4333-8333-333333333333" not in found.text


def test_client_import_job_requires_real_backup_and_valid_refs():
    source = {
        "action": "client_import",
        "revision": "a" * 64,
        "backup_id": "b" * 32,
        "client_import": {
            "source_inbound_id": 1,
            "target_inbound_id": 2,
            "expected_fingerprint": "c" * 64,
            "client_refs": ["n:3", "n:4"],
        },
    }
    assert JobRequest.model_validate(source).client_import.client_refs == ["n:3", "n:4"]
    for bad in (
        {"backup_id": None},
        {"client_import": {**source["client_import"], "client_refs": ["n:3", "n:3"]}},
        {"client_import": {**source["client_import"], "client_refs": ["bad"]}},
        {"client_import": None},
    ):
        with pytest.raises(ValidationError):
            JobRequest.model_validate({**source, **bad})


@pytest.fixture
def importer(owned, monkeypatch, tmp_path):
    context = owned.context
    source = backup(tmp_path / "source.db")
    context.payload["backup"] = base64.b64encode(source.read_bytes()).decode()
    remote = {
        "id": 2,
        "remark": "phone",
        "port": 10080,
        "listen": "127.0.0.1",
        "enable": True,
        "protocol": "vless",
        "settings": {"clients": [], "decryption": "none"},
        "streamSettings": {
            "network": "xhttp",
            "security": "none",
            "xhttpSettings": {"path": "/xhttp/"},
        },
    }
    context.payload["options"] = {
        "client_import": {
            "source_inbound_id": 1,
            "target_inbound_id": 2,
            "expected_fingerprint": public_inbound(remote)["fingerprint"],
            "client_refs": ["n:3", "n:4"],
        }
    }
    state = SimpleNamespace(
        clients=[],
        inbound=remote,
        calls=[],
        links={},
        fail_on_second=False,
        fail_link_after_write=False,
    )

    def request(route, payload=None):
        state.calls.append(route)
        if route == "inbounds/get/2":
            return copy.deepcopy(state.inbound)
        if route == "clients/list":
            return copy.deepcopy(state.clients)
        if route == "clients/add":
            if state.fail_on_second and payload["client"]["email"] == "beta":
                raise RuntimeError("simulated api failure")
            client = payload["client"]
            state.clients.append(
                {
                    "email": client["email"],
                    "uuid": client["id"],
                    "subId": client["subId"],
                }
            )
            state.inbound["settings"]["clients"].append(copy.deepcopy(client))
            return None
        if route.startswith("clients/get/"):
            email = route.rsplit("/", 1)[-1]
            row = next((row for row in state.clients if row["email"] == email), None)
            if row is None:
                raise RuntimeError("not found")
            return {
                "client": row,
                "inboundIds": [2],
                "externalLinks": copy.deepcopy(state.links.get(email, [])),
            }
        if route.startswith("clients/") and route.endswith("/externalLinks"):
            email = route.split("/")[1]
            state.links[email] = copy.deepcopy(payload["externalLinks"])
            if state.fail_link_after_write:
                state.fail_link_after_write = False
                raise RuntimeError("simulated link API timeout")
            return None
        if route.startswith("clients/del/"):
            email = route.rsplit("/", 1)[-1]
            state.links.pop(email, None)
            state.clients[:] = [row for row in state.clients if row["email"] != email]
            state.inbound["settings"]["clients"][:] = [
                row for row in state.inbound["settings"]["clients"] if row["email"] != email
            ]
            return None
        if route == "server/restartXrayService":
            return None
        raise AssertionError(route)

    monkeypatch.setattr(
        "app.agent.backup_client_import.managed_api",
        lambda *args: SimpleNamespace(request=request),
    )
    manager = BackupClientImporter(context, owned.operation.database, owned.inspector)
    return SimpleNamespace(manager=manager, state=state, owned=owned)


def test_import_keeps_uuid_subid_limits_and_adapts_flow(importer, capsys):
    importer.manager.apply(importer.owned.base)
    clients = importer.state.inbound["settings"]["clients"]
    assert len(clients) == 2
    assert clients[0]["id"] == "33333333-3333-4333-8333-333333333333"
    assert clients[0]["subId"] == "keepSubIdAlpha"
    assert clients[0]["flow"] == ""  # Vision flow is not for XHTTP/no TLS.
    assert clients[0]["totalGB"] == 1048576
    assert clients[0]["expiryTime"] == 1770000000000
    assert clients[1]["enable"] is False
    assert clients[1]["subId"] == "keepSubIdBeta"
    assert list(importer.owned.base.glob("before-client-import-*.db"))
    assert "keepSubIdAlpha" not in capsys.readouterr().out
    importer.manager.apply(importer.owned.base)
    assert len(importer.state.clients) == 2
    assert importer.state.calls.count("clients/add") == 2


def test_conflicting_subid_rejects_without_modifying_existing(importer):
    state = importer.state
    state.clients.append(
        {
            "email": "someone-else",
            "uuid": str(uuid.uuid4()),
            "subId": "keepSubIdAlpha",
        }
    )
    before = copy.deepcopy(state.clients)
    with pytest.raises(RuntimeError, match="conflicts"):
        importer.manager.apply(importer.owned.base)
    assert state.clients == before
    assert "clients/add" not in state.calls
    assert not list(importer.owned.base.glob("before-client-import-*.db"))


def test_partial_failure_rolls_back_only_new_identities(importer):
    importer.state.fail_on_second = True
    with pytest.raises(RuntimeError, match="simulated api failure"):
        importer.manager.apply(importer.owned.base)
    assert importer.state.clients == []
    assert importer.state.inbound["settings"]["clients"] == []
    assert "clients/del/alpha" in importer.state.calls


def test_signed_relative_expiry_and_telegram_id_are_preserved():
    source = {
        "id": "11111111-1111-4111-8111-111111111111",
        "subId": "preservedToken",
        "email": "valid-user",
        "expiryTime": -86400000,
        "tgId": -100100,
        "enable": True,
    }
    target = {
        "streamSettings": {"network": "xhttp", "security": "none"},
    }
    payload = new_payload(source, target, 9)
    assert payload["client"]["expiryTime"] == -86400000
    assert payload["client"]["tgId"] == -100100
    assert payload["client"]["subId"] == "preservedToken"
    assert payload["client"]["id"] == source["id"]


def link_backup(path, cross_client=False):
    """A 3x-ui 3.11 DB where one client aggregates another client subscription."""
    backup(path)
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO settings(key,value) VALUES (?,?)",
            ("subURI", "https://new.example.com:2096/sub/"),
        )
        db.execute(
            "CREATE TABLE client_external_links ("
            "id INTEGER PRIMARY KEY,client_id INTEGER,kind TEXT,value TEXT,"
            "remark TEXT,enable INTEGER,expiry_time INTEGER,name_prefix TEXT,"
            "sort_index INTEGER)"
        )
        db.execute(
            "INSERT INTO client_external_links VALUES (1,3,?,?,?,?,?,?,?)",
            ("subscription", "https://new.example.com:2096/sub/keepSubIdBeta", "", 1, 0, "", 0),
        )
        if cross_client:
            db.execute(
                "INSERT INTO client_external_links VALUES (2,4,?,?,?,?,?,?,?)",
                (
                    "subscription",
                    "https://new.example.com:2096/sub/keepSubIdAlpha",
                    "",
                    1,
                    0,
                    "",
                    0,
                ),
            )
    return path


def test_backup_external_links_are_private_and_dependencies_public(tmp_path):
    catalog = read_catalog(link_backup(tmp_path / "linked.db"))
    first = catalog[0]["clients"][0]
    assert first["data"]["_external_links"][0]["kind"] == "subscription"
    assert first["data"]["_external_links"][0]["_compatible"]
    public = public_catalog(catalog)
    assert public["inbounds"][0]["clients"][0]["external_link_count"] == 1
    assert public["inbounds"][0]["clients"][0]["depends_on"] == ["n:4"]
    assert "keepSubIdBeta" not in json.dumps(public)
    assert "https://new.example.com:2096/sub/" not in json.dumps(public)


def test_linked_import_preserves_refs_and_original_sub_ids(importer, tmp_path):
    source = link_backup(tmp_path / "with-links.db")
    importer.owned.context.payload["backup"] = base64.b64encode(source.read_bytes()).decode()
    importer.manager.apply(importer.owned.base)
    links = importer.state.links["alpha"]
    assert len(links) == 1
    assert links[0] == {
        "kind": "subscription",
        "value": "https://new.example.com:2096/sub/keepSubIdBeta",
        "remark": "",
        "enable": True,
        "expiryTime": 0,
        "namePrefix": "",
    }
    assert importer.state.clients[0]["subId"] == "keepSubIdAlpha"
    assert importer.state.clients[1]["subId"] == "keepSubIdBeta"
    assert "clients/alpha/externalLinks" in importer.state.calls
    importer.manager.apply(importer.owned.base)
    assert len(importer.state.links["alpha"]) == 1
    assert importer.state.calls.count("clients/alpha/externalLinks") == 1


def test_linked_import_rejects_absent_referenced_client(importer, tmp_path):
    source = link_backup(tmp_path / "with-links.db")
    context = importer.owned.context
    context.payload["backup"] = base64.b64encode(source.read_bytes()).decode()
    context.payload["options"]["client_import"]["client_refs"] = ["n:3"]
    with pytest.raises(RuntimeError, match="neither selected"):
        importer.manager.apply(importer.owned.base)
    assert importer.state.clients == []
    assert not list(importer.owned.base.glob("before-client-import-*.db"))


def test_linked_import_can_be_disabled_to_keep_only_own_uuid(importer, tmp_path):
    source = link_backup(tmp_path / "with-links.db")
    context = importer.owned.context
    context.payload["backup"] = base64.b64encode(source.read_bytes()).decode()
    context.payload["options"]["client_import"].update(
        client_refs=["n:3"], include_external_links=False
    )
    importer.manager.apply(importer.owned.base)
    assert [row["email"] for row in importer.state.clients] == ["alpha"]
    assert importer.state.links == {}


def test_circular_aggregate_subscriptions_fail_before_mutation(importer, tmp_path):
    source = link_backup(tmp_path / "cycle.db", cross_client=True)
    importer.owned.context.payload["backup"] = base64.b64encode(source.read_bytes()).decode()
    with pytest.raises(RuntimeError, match="Circular subscription"):
        importer.manager.apply(importer.owned.base)
    assert importer.state.clients == []


def test_restoring_links_to_existing_client_preserves_other_links(importer, tmp_path):
    source = link_backup(tmp_path / "linked.db")
    context = importer.owned.context
    context.payload["backup"] = base64.b64encode(source.read_bytes()).decode()
    importer.manager.apply(importer.owned.base)
    unrelated = {
        "kind": "subscription",
        "value": "https://public.example.org/sub/external",
        "remark": "existing",
        "enable": True,
        "expiryTime": 0,
        "namePrefix": "",
    }
    importer.state.links["alpha"] = [unrelated]
    importer.manager.apply(importer.owned.base)
    assert importer.state.links["alpha"][0] == unrelated
    assert len(importer.state.links["alpha"]) == 2
    assert importer.state.calls.count("clients/add") == 2


def test_partial_link_failure_restores_exact_old_links(importer, tmp_path):
    source = link_backup(tmp_path / "linked.db")
    importer.owned.context.payload["backup"] = base64.b64encode(source.read_bytes()).decode()
    # First import identities without linked subscriptions.
    importer.owned.context.payload["options"]["client_import"]["include_external_links"] = False
    importer.manager.apply(importer.owned.base)
    importer.owned.context.payload["options"]["client_import"]["include_external_links"] = True
    previous = copy.deepcopy(importer.state.links)
    importer.state.fail_link_after_write = True
    with pytest.raises(RuntimeError, match="simulated link API timeout"):
        importer.manager.apply(importer.owned.base)
    assert importer.state.links == previous
    assert len(importer.state.clients) == 2

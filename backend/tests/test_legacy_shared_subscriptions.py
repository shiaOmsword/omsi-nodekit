"""Synthetic regressions for legacy groups; no customer backup is committed."""

import base64
import copy
import json
import sqlite3

import pytest

from app.agent.backup_client_import import new_payload
from app.backup_clients import public_catalog, read_catalog, select_clients
from tests.test_backup_clients import backup
from tests.test_backup_clients import importer as importer
from tests.test_subscriptions import owned as owned


def shared_backup(path, normalized=True):
    backup(path, normalized=normalized)
    with sqlite3.connect(path) as db:
        if normalized:
            db.execute("UPDATE clients SET sub_id='keepSubIdAlpha'")
        else:
            settings = json.loads(db.execute("SELECT settings FROM inbounds").fetchone()[0])
            for client in settings["clients"]:
                client["subId"] = "keepSubIdAlpha"
            db.execute("UPDATE inbounds SET settings=?", (json.dumps(settings),))
    return path


def use_shared(importer, tmp_path):
    path = shared_backup(tmp_path / "shared.db")
    importer.owned.context.payload["backup"] = base64.b64encode(path.read_bytes()).decode()
    return read_catalog(path)


@pytest.mark.parametrize("normalized", [False, True])
def test_shared_source_adapts_ids_without_changing_uuids_or_backup(tmp_path, normalized):
    path = shared_backup(tmp_path / "source.db", normalized)
    original = path.read_bytes()
    catalog = read_catalog(path)
    refs = [c["ref"] for c in catalog[0]["clients"]]
    selected = select_clients(catalog, 1, refs)
    assert len({c["subId"] for c in selected}) == 2
    assert selected[0]["subId"] == "keepSubIdAlpha"
    assert selected[1]["subId"].startswith("nk-")
    assert selected[0]["id"] != selected[1]["id"]
    assert [c["data"]["id"] for c in catalog[0]["clients"]] == [c["id"] for c in selected]
    assert read_catalog(path) == catalog
    assert path.read_bytes() == original
    public = public_catalog(catalog)
    assert public["inbounds"][0]["clients"][1]["subscription_owner_refs"] == [refs[0]]
    assert all(c["shared_subscription"] for c in public["inbounds"][0]["clients"])
    for client in selected:
        assert client["subId"] not in json.dumps(public)
        assert client["id"] not in json.dumps(public)


def test_repeated_inbound_memberships_keep_identical_derived_tokens(tmp_path):
    path = shared_backup(tmp_path / "source.db")
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO inbounds(id,remark,protocol,settings) VALUES (2,'second','vless','{}')"
        )
        db.execute("INSERT INTO client_inbounds VALUES (4,2,'')")
    catalog = read_catalog(path)
    assert catalog[0]["clients"][1]["data"] == catalog[1]["clients"][0]["data"]
    assert not public_catalog(catalog)["inbounds"][1]["clients"][0]["subscription_owner_refs"]


def test_shared_import_uses_unique_api_ids_and_retains_original_public_group(importer, tmp_path):
    catalog = use_shared(importer, tmp_path)
    importer.manager.apply(importer.owned.base)
    state = importer.state
    clients = state.inbound["settings"]["clients"]
    assert [c["id"] for c in clients] == [c["data"]["id"] for c in catalog[0]["clients"]]
    assert clients[0]["subId"] == "keepSubIdAlpha"
    assert clients[1]["subId"] == catalog[0]["clients"][1]["data"]["subId"]
    assert clients[0]["flow"] == ""
    assert clients[1]["enable"] is False
    assert state.links["alpha"][0]["value"] == (
        "https://new.example.com:2096/sub/" + clients[1]["subId"]
    )
    importer.manager.apply(importer.owned.base)
    assert state.calls.count("clients/add") == 2
    assert state.calls.count("clients/alpha/externalLinks") == 1


def test_shared_links_remain_required_when_optional_source_links_are_disabled(importer, tmp_path):
    use_shared(importer, tmp_path)
    importer.owned.context.payload["options"]["client_import"]["include_external_links"] = False
    importer.manager.apply(importer.owned.base)
    assert len(importer.state.links["alpha"]) == 1


def test_shared_child_requires_owner_before_snapshot_or_writes(importer, tmp_path):
    use_shared(importer, tmp_path)
    importer.owned.context.payload["options"]["client_import"]["client_refs"] = ["n:4"]
    with pytest.raises(RuntimeError, match="select the subscription owner"):
        importer.manager.apply(importer.owned.base)
    assert "clients/add" not in importer.state.calls
    assert not list(importer.owned.base.glob("before-client-import-*.db"))


def test_shared_members_can_be_restored_in_batches_without_replacing_owner_links(
    importer, tmp_path
):
    use_shared(importer, tmp_path)
    change = importer.owned.context.payload["options"]["client_import"]
    change["client_refs"] = ["n:3"]
    importer.manager.apply(importer.owned.base)
    unrelated = {
        "kind": "subscription",
        "value": "https://other.example.com/sub/keep",
        "remark": "existing",
        "enable": True,
        "expiryTime": 0,
        "namePrefix": "",
    }
    importer.state.links["alpha"] = [unrelated]
    change["client_refs"] = ["n:4"]
    importer.manager.apply(importer.owned.base)
    assert importer.state.links["alpha"][0] == unrelated
    assert len(importer.state.links["alpha"]) == 2
    assert importer.state.calls.count("clients/add") == 2


def test_shared_link_failure_rolls_back_children_and_restores_existing_owner(importer, tmp_path):
    use_shared(importer, tmp_path)
    change = importer.owned.context.payload["options"]["client_import"]
    change["client_refs"] = ["n:3"]
    importer.manager.apply(importer.owned.base)
    before = copy.deepcopy(importer.state.clients)
    change["client_refs"] = ["n:4"]
    importer.state.fail_link_after_write = True
    with pytest.raises(RuntimeError, match="simulated link API timeout"):
        importer.manager.apply(importer.owned.base)
    assert importer.state.clients == before
    assert importer.state.links.get("alpha", []) == []


def test_new_shared_group_failure_rolls_back_all_new_identities(importer, tmp_path):
    use_shared(importer, tmp_path)
    importer.state.fail_link_after_write = True
    with pytest.raises(RuntimeError, match="simulated link API timeout"):
        importer.manager.apply(importer.owned.base)
    assert importer.state.clients == []
    assert importer.state.links == {}


def test_shared_migration_refuses_unrelated_destination_token_owner(importer, tmp_path):
    use_shared(importer, tmp_path)
    importer.state.clients.append(
        {"email": "foreign", "uuid": "different", "subId": "keepSubIdAlpha"}
    )
    with pytest.raises(RuntimeError, match="conflicts"):
        importer.manager.apply(importer.owned.base)
    assert "clients/add" not in importer.state.calls


def test_generated_group_edges_cannot_close_a_source_subscription_cycle(importer, tmp_path):
    path = shared_backup(tmp_path / "shared-cycle.db")
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO settings(key,value) VALUES ('subURI', 'https://new.example.com:2096/sub/')"
        )
        db.execute(
            "CREATE TABLE client_external_links (id INTEGER PRIMARY KEY,client_id INTEGER,kind TEXT,value TEXT,remark TEXT,enable INTEGER,expiry_time INTEGER,name_prefix TEXT,sort_index INTEGER)"
        )
        db.execute(
            "INSERT INTO client_external_links VALUES (1,4,'subscription','https://new.example.com:2096/sub/keepSubIdAlpha','',1,0,'',0)"
        )
    importer.owned.context.payload["backup"] = base64.b64encode(path.read_bytes()).decode()
    with pytest.raises(RuntimeError, match="Circular subscription"):
        importer.manager.apply(importer.owned.base)
    assert "clients/add" not in importer.state.calls
    assert not list(importer.owned.base.glob("before-client-import-*.db"))


def test_reality_keeps_vision_and_private_recovery_metadata_never_enters_api(tmp_path):
    catalog = read_catalog(shared_backup(tmp_path / "source.db"))
    client = catalog[0]["clients"][0]["data"]
    payload = new_payload(client, {"streamSettings": {"network": "tcp", "security": "reality"}}, 2)
    assert payload["client"]["flow"] == "xtls-rprx-vision"
    assert not any(k.startswith("_") for k in payload["client"])

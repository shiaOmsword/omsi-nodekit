"""Guarded restoration of clients from a stored SQLite dump to one VLESS inbound.

The source is never restored over the live DB. 3x-ui 3.11 Clients API owns
normalized client tables, subscriptions and runtime fanout. All secret identity
fields stay inside the authenticated SSH operation.
"""

import base64
import binascii
import json
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

from app.backup_clients import read_catalog, select_clients
from framework.messages import MessageKey
from framework.messages import text as message_text

from .inbound_manager import configuration, managed_api
from .inbound_meta import object_value, public_inbound


def identity(record):
    return (
        str(record.get("email", "")).lower(),
        str(record.get("uuid") or record.get("id") or "").lower(),
        record.get("subId"),
    )


def conflict_if_existing(selected, existing, target, target_id):
    """Exact matches already on this inbound are idempotent; nothing else is."""
    by_email = {}
    for record in existing:
        email = str(record.get("email", "")).lower()
        if not email or email in by_email:
            raise RuntimeError(message_text(MessageKey.CLIENT_IMPORT_CONFLICT))
        by_email[email] = record

    target_clients = object_value(target.get("settings")).get("clients", [])
    if not isinstance(target_clients, list):
        raise RuntimeError(message_text(MessageKey.CLIENT_IMPORT_CONFLICT))
    by_target = {}
    for client in target_clients:
        if not isinstance(client, dict):
            raise RuntimeError(message_text(MessageKey.CLIENT_IMPORT_CONFLICT))
        email = str(client.get("email", "")).lower()
        if email in by_target:
            raise RuntimeError(message_text(MessageKey.CLIENT_IMPORT_CONFLICT))
        by_target[email] = client

    pending, skipped = [], 0
    for item in selected:
        email, uid, sub = (
            item["email"].lower(), item["id"].lower(), item["subId"]
        )
        current = by_email.get(email)
        if current:
            current_id = str(current.get("uuid") or current.get("id") or "").lower()
            if current_id != uid or current.get("subId") != sub:
                raise RuntimeError(message_text(MessageKey.CLIENT_IMPORT_CONFLICT))
            target_entry = by_target.get(email)
            if (not target_entry or str(target_entry.get("id", "")).lower() != uid
                    or target_entry.get("subId") != sub):
                # An account on a different inbound requires a separate
                # attachment workflow; don't silently change its memberships.
                raise RuntimeError(message_text(MessageKey.CLIENT_IMPORT_CONFLICT))
            skipped += 1
            continue
        if email in by_target:
            raise RuntimeError(message_text(MessageKey.CLIENT_IMPORT_CONFLICT))
        for other in existing:
            other_uid = str(other.get("uuid") or other.get("id") or "").lower()
            if other.get("subId") == sub or other_uid == uid:
                raise RuntimeError(message_text(MessageKey.CLIENT_IMPORT_CONFLICT))
        pending.append(item)
    return pending, skipped


def new_payload(client, inbound, inbound_id):
    """Keep immutable identifiers and policy, adapt unsupported Vision flow."""
    data = dict(client)
    stream = object_value(inbound.get("streamSettings"))
    flow_supported = (
        stream.get("security") == "reality"
        and stream.get("network", "tcp") in {"tcp", "raw"}
    )
    if not flow_supported:
        data["flow"] = ""
    # These numeric/boolean values are account settings, not old traffic counters.
    for key in ("totalGB", "expiryTime", "limitIp", "reset", "resetDay",
                "resetWeekday", "resetMax", "tgId", "trafficResetDay"):
        value = data.get(key)
        if value is not None and (isinstance(value, bool)
                                  or not isinstance(value, int) or value < 0):
            raise RuntimeError(message_text(MessageKey.BACKUP_CLIENTS_INVALID))
    data["enable"] = bool(data.get("enable", True))
    # Source host rule IDs/traffic/counter IDs must not be copied across panels.
    data.pop("clientHostRuleIds", None)
    data.pop("clientStats", None)
    data.pop("idRecord", None)
    return {"client": data, "inboundIds": [inbound_id]}


class BackupClientImporter:
    def __init__(self, context, database, inspector):
        self.context, self.database, self.inspector = context, database, inspector

    def apply(self, base):
        context = self.context
        change = context.payload["options"]["client_import"]
        payload = context.payload.get("backup")
        if not isinstance(payload, str):
            raise RuntimeError(message_text(MessageKey.BACKUP_CLIENTS_INVALID))
        try:
            content = base64.b64decode(payload, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise RuntimeError(message_text(MessageKey.BACKUP_CLIENTS_INVALID)) from exc
        if len(content) > context.limits["backup_bytes"] or not content.startswith(
            b"SQLite format 3\x00"
        ):
            raise RuntimeError(message_text(MessageKey.BACKUP_CLIENTS_INVALID))

        with tempfile.TemporaryDirectory(prefix="nodekit-restore-clients-") as directory:
            source = Path(directory) / "source.db"
            source.write_bytes(content)
            source.chmod(0o600)
            try:
                self.database.validate(source)
                clients = select_clients(
                    read_catalog(source), change["source_inbound_id"], change["client_refs"]
                )
            except (ValueError, KeyError, TypeError) as exc:
                raise RuntimeError(message_text(MessageKey.BACKUP_CLIENTS_INVALID)) from exc

        api = managed_api(context, self.inspector, base)
        before = api.request(f"inbounds/get/{change['target_inbound_id']}")
        if (
            not isinstance(before, dict) or before.get("protocol") != "vless"
            or public_inbound(before)["fingerprint"] != change["expected_fingerprint"]
        ):
            raise RuntimeError(message_text(MessageKey.INBOUND_STALE))
        records = api.request("clients/list")
        if not isinstance(records, list) or len(records) > 5000 or any(
            not isinstance(v, dict) for v in records
        ):
            raise RuntimeError(message_text(MessageKey.BACKUP_CLIENTS_INVALID))
        pending, skipped = conflict_if_existing(
            clients, records, before, change["target_inbound_id"]
        )
        if not pending:
            context.emit(message_text(MessageKey.CLIENT_IMPORT_SUCCEEDED, count=0, skipped=skipped))
            return

        # Snapshot the entire target database before any API mutation.
        self.database.snapshot(
            self.inspector.database(), base / f"before-client-import-{time.time_ns()}.db"
        )
        # Stale private config or client set makes the operation unsafe.
        if (
            configuration(api.request(f"inbounds/get/{change['target_inbound_id']}"))
            != configuration(before)
            or api.request("clients/list") != records
        ):
            raise RuntimeError(message_text(MessageKey.INBOUND_STALE))

        created = []
        try:
            for client in pending:
                # Record the attempted identity before making the API request:
                # upstream may create the client and then fail during restart.
                created.append(client)
                api.request(
                    "clients/add",
                    new_payload(client, before, change["target_inbound_id"]),
                )
            after = api.request("clients/list")
            if not isinstance(after, list):
                raise RuntimeError(message_text(MessageKey.DEPLOYMENT_API_FAILED))
            by_email = {
                str(row.get("email", "")).lower(): row
                for row in after if isinstance(row, dict)
            }
            actual = api.request(f"inbounds/get/{change['target_inbound_id']}")
            attached = {
                str(item.get("email", "")).lower(): item
                for item in object_value(actual.get("settings")).get("clients", [])
            }
            for item in pending:
                global_row = by_email.get(item["email"].lower(), {})
                inbound_row = attached.get(item["email"].lower(), {})
                if (
                    identity(global_row) != (
                        item["email"].lower(), item["id"].lower(), item["subId"]
                    )
                    or str(inbound_row.get("id", "")).lower() != item["id"].lower()
                    or inbound_row.get("subId") != item["subId"]
                ):
                    raise RuntimeError(message_text(MessageKey.INBOUND_IDENTITIES))
            api.request("server/restartXrayService", {})
            context.emit(
                message_text(
                    MessageKey.CLIENT_IMPORT_SUCCEEDED,
                    count=len(pending), skipped=skipped,
                )
            )
        except Exception:
            # Roll back ONLY new identities still attached solely to this
            # inbound and matching the source's exact UUID + subId.
            for item in reversed(created):
                try:
                    path = "clients/get/" + quote(item["email"], safe="")
                    result = api.request(path)
                    if not isinstance(result, dict):
                        continue
                    saved = result.get("client", {})
                    if (
                        result.get("inboundIds") == [change["target_inbound_id"]]
                        and identity(saved) == (
                            item["email"].lower(), item["id"].lower(), item["subId"]
                        )
                    ):
                        api.request("clients/del/" + quote(item["email"], safe=""), {})
                    else:
                        context.emit(
                            message_text(MessageKey.DEPLOYMENT_ROLLBACK_FAILED), "error"
                        )
                except Exception:
                    context.emit(
                        message_text(MessageKey.DEPLOYMENT_ROLLBACK_FAILED), "error"
                    )
            try:
                api.request("server/restartXrayService", {})
            except Exception:
                context.emit(message_text(MessageKey.DEPLOYMENT_ROLLBACK_FAILED), "error")
            raise

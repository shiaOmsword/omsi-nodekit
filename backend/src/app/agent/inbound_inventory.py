"""Bounded, read-only summaries. UUIDs, passwords, private keys and sub IDs stay on the VPS."""

import json
import re

from .inbound_meta import public_inbound


def inbound_inventory(database, maximum):
    columns = {row[1] for row in database.execute("PRAGMA table_info(inbounds)")}
    required = {
        "id",
        "remark",
        "enable",
        "listen",
        "port",
        "protocol",
        "settings",
        "stream_settings",
    }
    if not required <= columns:
        raise ValueError()
    rows = database.execute(
        "SELECT id,remark,enable,listen,port,protocol,"
        "CASE WHEN length(settings)<=? THEN settings END,"
        "CASE WHEN length(stream_settings)<=? THEN stream_settings END, "
        + ("tag " if "tag" in columns else "'' ")
        + "FROM inbounds ORDER BY id LIMIT 101",
        (maximum // 2, maximum // 2),
    )
    summaries, probe_id, budget, clients_left, truncated = [], None, 0, 200, False
    for index, row in enumerate(rows):
        if index >= 100:
            truncated = True
            break
        identifier, remark, enabled, listen, port, protocol, raw_settings, raw_stream, tag = row
        if raw_settings is None or raw_stream is None:
            truncated = True
            continue
        budget += len(raw_settings.encode()) + len(raw_stream.encode())
        if budget > maximum:
            truncated = True
            break
        settings = json.loads(raw_settings or "{}")
        stream = json.loads(raw_stream or "{}")
        clients = settings.get("clients", [])
        if not isinstance(clients, list) or not isinstance(stream, dict):
            raise ValueError()
        safe_clients = []
        for client in clients:
            if not isinstance(client, dict):
                raise ValueError()
            sub_id = client.get("subId")
            usable = isinstance(sub_id, str) and bool(re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", sub_id))
            if probe_id is None and enabled and client.get("enable", True) and usable:
                probe_id = sub_id
            if clients_left:
                safe_clients.append(
                    {
                        "email": str(client.get("email", ""))[:160],
                        "enabled": bool(client.get("enable", True)),
                        "has_subscription": usable,
                    }
                )
                clients_left -= 1
            else:
                truncated = True
        summaries.append(
            {
                **public_inbound(
                    {
                        "id": identifier,
                        "remark": remark,
                        "enable": enabled,
                        "listen": listen,
                        "port": port,
                        "protocol": protocol,
                        "streamSettings": stream,
                        "tag": tag,
                    }
                ),
                "id": int(identifier),
                "remark": str(remark or "")[:160],
                "enabled": bool(enabled),
                "listen": str(listen or "0.0.0.0")[:80],
                "port": int(port),
                "protocol": str(protocol or "")[:32],
                "network": str(stream.get("network", ""))[:32],
                "security": str(stream.get("security", ""))[:32],
                "client_count": len(clients),
                "clients": safe_clients,
                "xhttp_path": (stream.get("xhttpSettings") or {}).get("path", "")[:80]
                if isinstance(stream.get("xhttpSettings"), dict)
                else "",
                "xhttp_mode": (stream.get("xhttpSettings") or {}).get("mode", "")[:30]
                if isinstance(stream.get("xhttpSettings"), dict)
                else "",
            }
        )
    return summaries, probe_id, truncated

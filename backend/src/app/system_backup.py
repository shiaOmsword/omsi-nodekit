"""Versioned private recovery bundle shared by local storage and the SSH agent."""

import hashlib
import io
import json
import zipfile

from framework.messages import MessageKey
from framework.messages import text as message_text

MEMBERS = {"manifest.json", "x-ui.db", "system.json"}


def pack(database, system, limit):
    entries = {"x-ui.db": database, "system.json": json.dumps(system).encode()}
    manifest = {
        "format": "omsi-nodekit",
        "version": 1,
        "sha256": {name: hashlib.sha256(data).hexdigest() for name, data in entries.items()},
    }
    entries["manifest.json"] = json.dumps(manifest).encode()
    if sum(map(len, entries.values())) > limit:
        raise ValueError(message_text(MessageKey.SYSTEM_BACKUP_INVALID))
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    content = output.getvalue()
    unpack(content, limit)
    return content


def unpack(content, limit):
    try:
        if len(content) > limit:
            raise ValueError()
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if (
                len(entries) != len(MEMBERS)
                or {e.filename for e in entries} != MEMBERS
                or sum(e.file_size for e in entries) > limit
                or any(
                    e.flag_bits & 1 or (e.external_attr >> 16) & 0o170000 == 0o120000
                    for e in entries
                )
            ):
                raise ValueError()
            manifest = json.loads(archive.read("manifest.json"))
            database, raw_system = archive.read("x-ui.db"), archive.read("system.json")
        if (
            manifest.get("format") != "omsi-nodekit"
            or manifest.get("version") != 1
            or manifest.get("sha256")
            != {
                "x-ui.db": hashlib.sha256(database).hexdigest(),
                "system.json": hashlib.sha256(raw_system).hexdigest(),
            }
            or not database.startswith(b"SQLite format 3\x00")
        ):
            raise ValueError()
        system = json.loads(raw_system)
        if (
            not isinstance(system, dict)
            or system.get("version") != 1
            or not isinstance(system.get("node"), dict)
            or system.get("tcp_algorithm") not in {None, "cubic", "bbr"}
            or not isinstance(system.get("tunnel_files"), dict)
            or not isinstance(system.get("reference_files"), dict)
        ):
            raise ValueError()
        return database, system
    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        zipfile.BadZipFile,
        RuntimeError,
    ) as exc:
        raise ValueError(message_text(MessageKey.SYSTEM_BACKUP_INVALID)) from exc


def database_content(content, limit):
    return unpack(content, limit)[0] if content.startswith(b"PK") else content

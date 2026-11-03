import base64
import os
import platform
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from app.system_backup import pack, unpack
from framework.messages import MessageKey
from framework.messages import text as message_text

from .firewall import FirewallTransaction, desired_rules
from .tcp_tuning import MODULE_CONTENT, SYSCTL_CONTENT, TCPConfigurator

REFERENCE_FILES = (
    "manifest.json",
    "deployment.json",
    "compose.yaml",
    "Caddyfile",
    "Caddyfile.site",
    "inbound-identities.json",
    "xhttp-routes.json",
    "xhttp-hosts.json",
    "firewall-rules.json",
    "tunnel-connections.json",
    "subscriptions.json",
)


def safe_file(path, limit):
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError(message_text(MessageKey.SYSTEM_BACKUP_CONFLICT))
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError(message_text(MessageKey.SYSTEM_BACKUP_CONFLICT))
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError(message_text(MessageKey.SYSTEM_BACKUP_INVALID))
    return data


def create_bundle(context, database, inspector):
    base, limit = context.directory(), context.limits["backup_bytes"]
    tcp = TCPConfigurator(context).inspect()
    system = {
        "version": 1,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "kernel": platform.release(),
        "architecture": platform.machine(),
        "node": context.node,
        "tcp_algorithm": tcp["current"] if tcp else None,
        "reference_files": {},
        "tunnel_files": {},
    }
    if system["tcp_algorithm"] not in {None, "cubic", "bbr"}:
        system["tcp_algorithm"] = None
    references = set(REFERENCE_FILES)
    references.update(
        p.name
        for pattern in ("tunnel-*.json", "pool-*.json")
        for p in base.glob(pattern)
        if re.fullmatch(r"(?:tunnel|pool)-[a-z][a-z0-9-]{0,39}\.json", p.name)
    )
    for name in sorted(references):
        path = base / name
        if path.exists() or path.is_symlink():
            system["reference_files"][name] = base64.b64encode(safe_file(path, limit)).decode()
    for tunnel in context.node["tunnels"]:
        system["tunnel_files"][tunnel["name"]] = {
            field: base64.b64encode(safe_file(Path(tunnel[field]), limit)).decode()
            for field in ("identity_file", "known_hosts_file")
        }
    with tempfile.TemporaryDirectory(prefix="nodekit-system-") as folder:
        snapshot = Path(folder) / "x-ui.db"
        database.snapshot(inspector.database(), snapshot)
        return pack(snapshot.read_bytes(), system, limit)


class SystemRestorer:
    def __init__(self, context, inspector):
        self.context, self.inspector = context, inspector

    def apply(self):
        import pwd

        context = self.context
        _, system = unpack(
            base64.b64decode(context.payload["backup"], validate=True),
            context.limits["backup_bytes"],
        )
        source, destination = system["node"], context.node
        if any(p.is_symlink() for p in (context.directory(), *context.directory().parents)):
            raise RuntimeError(message_text(MessageKey.SYSTEM_BACKUP_CONFLICT))
        if source.get("id") != destination["id"]:
            raise RuntimeError(message_text(MessageKey.SYSTEM_BACKUP_CONFLICT))
        requested = context.payload["options"]["system_restore"]
        tcp = TCPConfigurator(context)
        before = tcp.inspect()
        if not before or before["fingerprint"] != requested["expected_fingerprint"]:
            raise RuntimeError(message_text(MessageKey.TCP_TUNING_STALE))
        if before["conflict"] or system["tcp_algorithm"] not in {"cubic", "bbr"}:
            raise RuntimeError(message_text(MessageKey.SYSTEM_BACKUP_CONFLICT))
        candidates, destinations = [], {}
        original_tunnels = {t["name"]: t for t in source.get("tunnels", [])}
        for tunnel in destination["tunnels"]:
            old = original_tunnels.get(tunnel["name"])
            if not old or any(old.get(k) != tunnel.get(k) for k in ("host", "user", "ssh_port")):
                raise RuntimeError(message_text(MessageKey.SYSTEM_BACKUP_CONFLICT))
            user = pwd.getpwnam(tunnel["user"])
            for field in ("identity_file", "known_hosts_file"):
                path = Path(tunnel[field])
                data = base64.b64decode(
                    system["tunnel_files"][tunnel["name"]][field], validate=True
                )
                if (
                    len(data) > context.limits["backup_bytes"]
                    or not data
                    or any(p.is_symlink() for p in (path, *path.parents))
                    or (path.exists() and safe_file(path, context.limits["backup_bytes"]) != data)
                    or (path in destinations and destinations[path] != data)
                ):
                    raise RuntimeError(message_text(MessageKey.SYSTEM_BACKUP_CONFLICT))
                destinations[path] = data
                if not path.exists() and path not in [p for p, *_ in candidates]:
                    candidates.append((path, data, user.pw_uid, user.pw_gid))
        old_config, _ = tcp._read_owned(tcp.sysctl_path, SYSCTL_CONTENT.values())
        old_module, _ = tcp._read_owned(tcp.module_path, (MODULE_CONTENT,))
        created, directories, applied_tcp = [], [], False
        firewall = FirewallTransaction(
            context,
            context.directory(),
            enabled=(destination.get("deployment") or {}).get("manage_ufw", True)
            and (context.directory() / "manifest.json").is_file(),
        )
        try:
            for path, data, uid, gid in candidates:
                missing = [p for p in path.parents if not p.exists()]
                for parent in reversed(missing):
                    parent.mkdir(mode=0o700)
                    os.chown(parent, uid, gid)
                    directories.append(parent)
                with path.open("xb") as stream:
                    created.append((path, data))
                    os.fchmod(stream.fileno(), 0o600)
                    os.fchown(stream.fileno(), uid, gid)
                    stream.write(data)
            context.payload["options"]["tcp_tuning"] = {
                "algorithm": system["tcp_algorithm"],
                "expected_fingerprint": before["fingerprint"],
            }
            tcp.apply()
            applied_tcp = True
            firewall.ensure(desired_rules(context, self.inspector.report))
            firewall.commit()
        except Exception:
            try:
                firewall.rollback()
            except Exception:
                context.emit(message_text(MessageKey.DEPLOYMENT_ROLLBACK_FAILED), "error")
            try:
                if applied_tcp:
                    for path, replacement, original in (
                        (tcp.sysctl_path, SYSCTL_CONTENT[system["tcp_algorithm"]], old_config),
                        (
                            tcp.module_path,
                            MODULE_CONTENT if system["tcp_algorithm"] == "bbr" else None,
                            old_module,
                        ),
                    ):
                        tcp._replace(path, replacement, original)
                    if tcp.inspect()["current"] != system["tcp_algorithm"]:
                        raise ValueError()
                    context.command(
                        ["sysctl", "-w", f"net.ipv4.tcp_congestion_control={before['current']}"]
                    )
            except Exception:
                context.emit(message_text(MessageKey.DEPLOYMENT_ROLLBACK_FAILED), "error")
            for path, data in reversed(created):
                if path.is_file() and not path.is_symlink() and path.read_bytes() == data:
                    path.unlink()
            for path in reversed(directories):
                try:
                    path.rmdir()
                except OSError:
                    pass
            raise
        finally:
            context.payload["options"].pop("tcp_tuning", None)
        context.emit(message_text(MessageKey.SYSTEM_BACKUP_RESTORED))

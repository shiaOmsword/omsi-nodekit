import sqlite3
from contextlib import closing
from pathlib import Path

from app.defaults import XUI_DATABASE_FILE
from framework.messages import MessageKey
from framework.messages import text as message_text

from .certificates import CertificateInspector
from .inbound_inventory import inbound_inventory

SETTING_KEYS = (
    "webListen",
    "webPort",
    "webBasePath",
    "webDomain",
    "webCertFile",
    "webKeyFile",
    "subListen",
    "subPort",
    "subPath",
    "subDomain",
    "subCertFile",
    "subKeyFile",
    "subEnable",
    "subURI",
)


class PanelInspector:
    def __init__(self, inventory):
        self.inventory = inventory
        self.context = inventory.context
        self.targets = {}
        self.containers = {}
        self.probe_ids = {}

    def _settings(self, finding, source, resolve, database_type="sqlite"):
        finding.update(settings={}, certificates=[], warnings=[])
        if database_type not in {"", "sqlite", "sqlite3"}:
            finding["warnings"].append(message_text(MessageKey.INSPECTION_POSTGRES))
            return
        if not source or not source.is_file():
            finding["warnings"].append(message_text(MessageKey.INSPECTION_DATABASE_FAILED))
            return
        try:
            with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as db:
                db.execute("PRAGMA query_only=ON")
                marks = ",".join("?" for _ in SETTING_KEYS)
                settings = dict(
                    db.execute(
                        f"SELECT key,value FROM settings WHERE key IN ({marks})", SETTING_KEYS
                    )
                )
                try:
                    items, probe_id, truncated = inbound_inventory(db, self.inventory.maximum)
                    finding.update(
                        inbounds=items, inbounds_readable=True, inbounds_truncated=truncated
                    )
                    self.probe_ids[finding["id"]] = probe_id
                    if truncated:
                        finding["warnings"].append(message_text(MessageKey.INBOUNDS_UNREADABLE))
                except (sqlite3.DatabaseError, ValueError, TypeError, AttributeError):
                    finding["warnings"].append(message_text(MessageKey.INBOUNDS_UNREADABLE))
            maximum = self.inventory.maximum
            if any(
                not isinstance(v, str) or len(v.encode("utf-8")) > maximum // 16
                for v in settings.values()
            ):
                raise ValueError(message_text(MessageKey.INSPECTION_TOO_LARGE))
            defaults = self.inventory.policy["panel_defaults"]
            finding["defaulted_settings"] = [
                key for key in SETTING_KEYS if key not in settings and key in defaults
            ]
            settings = {**defaults, **settings}
            finding["settings"] = settings
            certificates = CertificateInspector(self.inventory)
            for usage, cert, key in (
                ("panel", "webCertFile", "webKeyFile"),
                ("subscription", "subCertFile", "subKeyFile"),
            ):
                finding["certificates"].append(
                    certificates.inspect(
                        usage, settings.get(cert, ""), settings.get(key, ""), resolve
                    )
                )
            self.targets[finding["id"]] = (source, resolve)
        except (sqlite3.DatabaseError, OSError, ValueError):
            finding["warnings"].append(message_text(MessageKey.INSPECTION_DATABASE_FAILED))

    def discover(self, containers):
        result = []
        owned_service = self.inventory.service(self.context.unit("panel"))
        if owned_service:
            owned = {
                "id": f"managed:{self.context.node['id']}",
                "installation": "managed",
                "service": self.context.unit("panel"),
                "active": owned_service.get("ActiveState") == "active",
                "database_path": str(self.context.directory() / "db" / XUI_DATABASE_FILE),
            }
            self._settings(owned, Path(owned["database_path"]), Path)
            result.append(owned)
        config = self.context.node["panel"]
        service_name = config["service"]
        service = self.inventory.service(service_name)
        default_database = self.inventory.policy["native_database"]
        env = self.inventory.environment(service, self.inventory.policy["native_environment_files"])
        native_path = (
            config.get("database_path") if config["installation"] in {"native", "auto"} else None
        )
        if not native_path:
            folder = env.get("XUI_DB_FOLDER")
            native_path = str(Path(folder) / XUI_DATABASE_FILE) if folder else default_database
        known_binary = Path(self.inventory.policy["native_binary"]).is_file()
        if service or (
            (config["installation"] == "native" or known_binary) and Path(native_path).is_file()
        ):
            finding = {
                "id": f"native:{service_name}",
                "installation": "native",
                "active": service.get("ActiveState") == "active",
                "service": service_name,
                "database_path": native_path,
            }
            self._settings(
                finding,
                Path(native_path),
                lambda p: Path(p) if p.startswith("/") else None,
                env.get("XUI_DB_TYPE", "sqlite"),
            )
            result.append(finding)
        managed_found = False
        for container in containers:
            details = self.inventory.describe_container(container)
            labels = container.get("Config", {}).get("Labels") or {}
            managed = (
                labels.get("com.docker.compose.project") == self.context.project()
                and labels.get("com.docker.compose.service") == "panel"
            )
            matches = config.get("container") in {container.get("Id"), details["container"]}
            if not managed and not matches and "3x-ui" not in details["image"].lower():
                continue
            managed_found = managed_found or managed
            env = self.inventory.container_environment(container)
            container_path = (
                config.get("database_path") if config["installation"] == "docker" else None
            )
            if not container_path:
                folder = env.get("XUI_DB_FOLDER")
                container_path = (
                    str(Path(folder) / XUI_DATABASE_FILE)
                    if folder
                    else self.inventory.policy["container_database"]
                )
            finding = {
                "id": f"docker:{container['Id']}",
                "installation": "managed" if managed else "docker",
                "database_path": container_path,
                **details,
            }
            self.containers[finding["id"]] = container

            def resolve(p, c=container):
                return self.inventory.container_path(c, p)

            self._settings(
                finding, resolve(container_path), resolve, env.get("XUI_DB_TYPE", "sqlite")
            )
            result.append(finding)
        managed_db = self.context.directory() / "db" / XUI_DATABASE_FILE
        if not managed_found and not owned_service and managed_db.is_file():
            finding = {
                "id": f"managed:{self.context.node['id']}",
                "installation": "managed",
                "active": False,
                "database_path": str(managed_db),
            }
            self._settings(
                finding, managed_db, lambda p: self.context.directory() / "cert" / Path(p).name
            )
            result.append(finding)
        return result

    def select(self, findings):
        config = self.context.node["panel"]
        mode = config["installation"]
        matches = [f for f in findings if mode == "auto" or f["installation"] == mode]
        if config.get("container"):
            matches = [
                f
                for f in matches
                if f.get("container") == config["container"]
                or f["id"] == f"docker:{config['container']}"
            ]
        return matches[0] if len(matches) == 1 else None

    def database(self, finding):
        if finding is None or finding["id"] not in self.targets:
            raise RuntimeError(message_text(MessageKey.INSPECTION_REQUIRED))
        return self.targets[finding["id"]][0]

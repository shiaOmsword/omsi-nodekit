import sqlite3
from contextlib import closing

from app.defaults import NODE_DEFAULTS as D
from app.defaults import XUI_LEGACY_PANEL_PATH, XUI_SETTINGS_COLUMNS, XUI_TABLES
from framework.messages import MessageKey
from framework.messages import text as message_text

from .context import AgentContext
from .subscriptions import public_base


class PanelDatabase:
    def __init__(self, context: AgentContext):
        self.context = context

    def validate(self, path):
        self.context.snapshots.validate(path, tables=XUI_TABLES, columns=XUI_SETTINGS_COLUMNS)

    def snapshot(self, source, destination):
        self.context.snapshots.snapshot(source, destination)
        self.validate(destination)

    def configure_subscriptions(self, path, node):
        changes = {
            "subListen": node["deployment"]["subscription_bind"],
            "subPort": str(node["panel"]["subscription_port"]),
            "subPath": node["panel"]["subscription_path"],
            "subEnable": "true",
            "subCertFile": "",
            "subKeyFile": "",
            "subDomain": "",
            "subURI": public_base(node),
        }
        with closing(sqlite3.connect(path)) as db, db:
            marks = ",".join("?" for _ in changes)
            original = dict(
                db.execute(f"SELECT key,value FROM settings WHERE key IN ({marks})", tuple(changes))
            )
            for key, value in changes.items():
                cursor = db.execute("UPDATE settings SET value=? WHERE key=?", (value, key))
                if not cursor.rowcount:
                    db.execute("INSERT INTO settings (key,value) VALUES (?,?)", (key, value))
        return {key: original.get(key) for key in changes}

    @staticmethod
    def restore_settings(path, original):
        with closing(sqlite3.connect(path)) as db, db:
            for key, value in original.items():
                db.execute("DELETE FROM settings WHERE key=?", (key,))
                if value is not None:
                    db.execute("INSERT INTO settings (key,value) VALUES (?,?)", (key, value))

    def configure_listeners(self, path, node, restoring):
        panel = node["panel"]
        changes = {
            "webListen": "127.0.0.1",
            "webPort": str(panel["port"]),
            "webCertFile": "",
            "webKeyFile": "",
            "webDomain": "",
            "subListen": "127.0.0.1",
            "subPort": str(panel["subscription_port"]),
            "subCertFile": "",
            "subKeyFile": "",
            "subDomain": "",
        }
        target = node.get("deployment")
        if target:
            changes["subListen"] = target["subscription_bind"]
        # Keep existing panel paths, subscription IDs/paths, clients and Xray settings on restore.
        if not restoring:
            changes.update(
                webBasePath=panel["base_path"], subPath=panel["subscription_path"], subEnable="true"
            )
        with closing(sqlite3.connect(path)) as db, db:
            if restoring:
                current = dict(db.execute("SELECT key,value FROM settings"))
                expected = current.get("subPath", D.subscription_path)
                if expected != panel["subscription_path"]:
                    raise RuntimeError(message_text(MessageKey.SUBSCRIPTION_PATH_MISMATCH))
                actual = current.get("webBasePath", XUI_LEGACY_PANEL_PATH)
                if actual != panel["base_path"]:
                    raise RuntimeError(message_text(MessageKey.PANEL_PATH_MISMATCH))
            if node["caddy"]["enabled"]:
                changes["subURI"] = public_base(node)
            for key, value in changes.items():
                cursor = db.execute("UPDATE settings SET value=? WHERE key=?", (value, key))
                if not cursor.rowcount:
                    db.execute("INSERT INTO settings (key,value) VALUES (?,?)", (key, value))

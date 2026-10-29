import sqlite3
from pathlib import Path

import pytest
import yaml

from app.entities.node import Node


@pytest.fixture
def node():
    return Node.model_validate(
        {"id": "test-node", "name": "Test node", "ssh": {"host": "203.0.113.10"}}
    )


@pytest.fixture
def node_yaml(node):
    return yaml.safe_dump(node.model_dump())


def create_database(path: Path, settings=None):
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE settings (id INTEGER PRIMARY KEY, key TEXT UNIQUE, value TEXT);
            CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, password TEXT);
            CREATE TABLE inbounds (id INTEGER PRIMARY KEY, settings TEXT, stream_settings TEXT);
            INSERT INTO users VALUES (1,'original-admin','original-hash');
            INSERT INTO inbounds VALUES (1,'client-uuid-and-sub-id','reality-private-key');
        """)
        for key, value in (
            settings
            or {
                "webBasePath": "/nodekit/",
                "subPath": "/sub/",
                "xrayTemplateConfig": "original-outbound",
            }
        ).items():
            db.execute("INSERT INTO settings (key,value) VALUES (?,?)", (key, value))
    return path


@pytest.fixture
def db_file(tmp_path):
    return create_database(tmp_path / "x-ui.db")

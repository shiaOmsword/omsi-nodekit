from framework.database import Migration

MIGRATIONS = [
    Migration(
        1,
        """
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, yaml TEXT NOT NULL, revision TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY, node_id TEXT NOT NULL, action TEXT NOT NULL,
    status TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT, backup_id TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
    level TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS backups (
    id TEXT PRIMARY KEY, filename TEXT NOT NULL, size INTEGER NOT NULL,
    sha256 TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS events_by_job ON events(job_id, seq);
""",
    ),
    Migration(
        2,
        """
CREATE TABLE ssh_keys (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, public_key TEXT NOT NULL,
    fingerprint TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE job_reports (
    job_id TEXT PRIMARY KEY REFERENCES jobs(id), report TEXT NOT NULL
);
""",
    ),
    Migration(
        3,
        """
ALTER TABLE nodes ADD COLUMN state TEXT NOT NULL DEFAULT 'active'
CHECK (state IN ('active', 'hidden', 'archived'));
""",
    ),
]

"""SQLite cache: connections, schema management, and small query helpers.

The database is a pure cache: every row can be rebuilt by re-ingesting the
repositories under ``instance/repos``. Schema changes are therefore handled
by bumping ``Config.SCHEMA_VERSION`` — the next boot drops the stale tables
and recreates them, instead of running migrations.

Metric-cache tables (commits, changes, authors) arrive with the analyzer in
Stage 3; they will be added to ``_SCHEMA`` here.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE repos (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    source_type     TEXT NOT NULL,                 -- 'upload' | 'url'
    source          TEXT,                          -- original filename or URL
    path            TEXT NOT NULL,                 -- git repository on disk
    status          TEXT NOT NULL,                 -- pending | running | ready | failed
    error           TEXT,                          -- failure detail when failed
    head_sha        TEXT,                          -- reference commit (default HEAD)
    commit_count    INTEGER,                       -- commits reachable from HEAD
    non_merge_count INTEGER,                       -- analysis universe size
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL
);

CREATE TABLE ingest_jobs (
    id         TEXT PRIMARY KEY,
    repo_id    TEXT NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,                      -- 'upload' | 'url'
    status     TEXT NOT NULL,                      -- pending | running | done | failed
    phase      TEXT,                               -- current step (for the UI)
    progress   REAL NOT NULL DEFAULT 0,            -- 0..1 (approximate)
    message    TEXT,                               -- failure detail when failed
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE INDEX idx_ingest_jobs_repo ON ingest_jobs (repo_id);
"""


def connect(db_path) -> sqlite3.Connection:
    """Open a connection that is safe to share across threads (WAL + timeouts)."""
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path, schema_version: int) -> None:
    """Create the cache schema; on a version change, rebuild it from scratch."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    try:
        if _stored_version(conn) == schema_version:
            return
        conn.execute("PRAGMA foreign_keys=OFF")  # allow dropping FK-related tables
        with conn:
            for (name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%'"
            ).fetchall():
                conn.execute(f'DROP TABLE IF EXISTS "{name}"')
            conn.executescript(_SCHEMA)
            conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)", (schema_version,)
            )
    finally:
        conn.close()


def query_one(db_path, sql: str, params=()) -> dict | None:
    conn = connect(db_path)
    try:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def query_all(db_path, sql: str, params=()) -> list[dict]:
    conn = connect(db_path)
    try:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def execute(db_path, sql: str, params=()) -> None:
    """Run a single write statement inside a transaction."""
    conn = connect(db_path)
    try:
        with conn:
            conn.execute(sql, params)
    finally:
        conn.close()


def _stored_version(conn) -> int | None:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'schema_version'"
    ).fetchone()
    if row is None:
        return None
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    return row[0] if row is not None else None

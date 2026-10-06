"""Repository registry: CRUD over the ``repos`` table.

Every read returns the repo row plus its latest ingest job (nested as
``job``), which is what the UI polls for progress/status.
"""

from __future__ import annotations

import time
from pathlib import Path

from .. import db

# Repo row + latest ingest job in one query (no N+1 when listing).
_JOB_JOIN = """
    SELECT r.*,
           j.id       AS job_id,
           j.status   AS job_status,
           j.phase    AS job_phase,
           j.progress AS job_progress
      FROM repos r
      LEFT JOIN ingest_jobs j ON j.id = (
            SELECT id FROM ingest_jobs
             WHERE repo_id = r.id
             ORDER BY created_at DESC, rowid DESC
             LIMIT 1)
"""

_FIELDS = (
    "id",
    "name",
    "source_type",
    "source",
    "path",
    "status",
    "error",
    "head_sha",
    "commit_count",
    "non_merge_count",
    "created_at",
    "updated_at",
)


def insert_repo(
    db_path, *, repo_id: str, name: str, source_type: str, source: str, path: Path
) -> dict:
    """Register a new repo in the ``pending`` state and return it."""
    now = int(time.time())
    db.execute(
        db_path,
        "INSERT INTO repos (id, name, source_type, source, path, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)",
        (repo_id, name, source_type, source, str(path), now, now),
    )
    return get_repo(db_path, repo_id)


def get_repo(db_path, repo_id: str) -> dict | None:
    row = db.query_one(db_path, _JOB_JOIN + " WHERE r.id = ?", (repo_id,))
    return _shape(row) if row is not None else None


def list_repos(db_path) -> list[dict]:
    rows = db.query_all(
        db_path, _JOB_JOIN + " ORDER BY r.created_at DESC, r.rowid DESC"
    )
    return [_shape(row) for row in rows]


def update_repo(db_path, repo_id: str, **fields) -> None:
    """Update columns on a repo row (``None`` values clear the column)."""
    fields["updated_at"] = int(time.time())
    columns = ", ".join(f"{key} = ?" for key in fields)
    db.execute(
        db_path, f"UPDATE repos SET {columns} WHERE id = ?", (*fields.values(), repo_id)
    )


def delete_repo(db_path, repo_id: str) -> bool:
    """Delete the repo row (jobs cascade via foreign key). Returns True if a row went."""
    conn = db.connect(db_path)
    try:
        with conn:
            cursor = conn.execute("DELETE FROM repos WHERE id = ?", (repo_id,))
            return cursor.rowcount > 0
    finally:
        conn.close()


def _shape(row: dict) -> dict:
    repo = {key: row[key] for key in _FIELDS}
    repo["job"] = (
        {
            "id": row["job_id"],
            "status": row["job_status"],
            "phase": row["job_phase"],
            "progress": row["job_progress"],
        }
        if row["job_id"]
        else None
    )
    return repo

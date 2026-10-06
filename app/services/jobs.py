"""Background ingest jobs: bookkeeping plus a daemon-thread runner.

Progress is persisted in the ``ingest_jobs`` table so the UI can poll
``GET /api/jobs/<id>`` from any tab; nothing is kept only in memory.

Contract for tasks passed to :func:`run_async`:

- they receive a ``JobReporter`` and do their own repo-row updates on success;
- failures raise an exception whose message is friendly (``IngestError``);
  the runner then marks both the job and the repo as ``failed``.
"""

from __future__ import annotations

import logging
import shutil
import threading
import time
import uuid
from pathlib import Path

from .. import db
from . import registry

log = logging.getLogger(__name__)

ACTIVE_STATUSES = ("pending", "running")


def new_id() -> str:
    return uuid.uuid4().hex


def create_job(db_path, repo_id: str, kind: str) -> dict:
    job_id = new_id()
    now = int(time.time())
    db.execute(
        db_path,
        "INSERT INTO ingest_jobs "
        "(id, repo_id, kind, status, phase, progress, created_at, updated_at) "
        "VALUES (?, ?, ?, 'pending', 'queued', 0, ?, ?)",
        (job_id, repo_id, kind, now, now),
    )
    return get_job(db_path, job_id)


def get_job(db_path, job_id: str) -> dict | None:
    return db.query_one(db_path, "SELECT * FROM ingest_jobs WHERE id = ?", (job_id,))


def update_job(
    db_path,
    job_id: str,
    *,
    status: str | None = None,
    phase: str | None = None,
    progress: float | None = None,
    message: str | None = None,
) -> None:
    fields: dict = {}
    if status is not None:
        fields["status"] = status
    if phase is not None:
        fields["phase"] = phase
    if progress is not None:
        fields["progress"] = progress
    if message is not None:
        fields["message"] = message
    if not fields:
        return
    fields["updated_at"] = int(time.time())
    columns = ", ".join(f"{key} = ?" for key in fields)
    db.execute(
        db_path,
        f"UPDATE ingest_jobs SET {columns} WHERE id = ?",
        (*fields.values(), job_id),
    )


class JobReporter:
    """Throttled progress writer handed to ingest tasks."""

    def __init__(self, db_path, job_id: str):
        self._db_path = db_path
        self._job_id = job_id
        self._last_phase: str | None = None
        self._last_progress: float | None = None

    def set(self, *, phase: str | None = None, progress: float | None = None) -> None:
        effective_phase = phase if phase is not None else self._last_phase
        effective_progress = progress if progress is not None else self._last_progress

        if effective_phase == self._last_phase:
            if effective_progress == self._last_progress:
                return
            if (
                effective_progress is not None
                and self._last_progress is not None
                and abs(effective_progress - self._last_progress) < 0.01
            ):
                return

        update_job(self._db_path, self._job_id, phase=phase, progress=progress)
        self._last_phase = effective_phase
        self._last_progress = effective_progress


def run_async(db_path, job_id: str, repo_id: str, task) -> None:
    """Run ``task(reporter)`` on a daemon thread with job/repo bookkeeping.

    Success -> job ``done`` (the task itself marks the repo ``ready``).
    Failure -> job and repo ``failed`` with the exception message.
    """

    def runner() -> None:
        try:
            update_job(db_path, job_id, status="running")
            registry.update_repo(db_path, repo_id, status="running", error=None)
            task(JobReporter(db_path, job_id))
        except Exception as exc:  # noqa: BLE001 — the message is shown in the UI
            log.exception("Ingest job %s failed", job_id)
            message = str(exc).strip() or exc.__class__.__name__
            try:
                update_job(db_path, job_id, status="failed", message=message)
                registry.update_repo(db_path, repo_id, status="failed", error=message)
            except Exception:  # pragma: no cover — last-resort bookkeeping
                log.exception("Could not record failure for job %s", job_id)
        else:
            update_job(db_path, job_id, status="done", phase="finished", progress=1.0)

    threading.Thread(target=runner, name=f"rat-job-{job_id[:8]}", daemon=True).start()


RECOVERY_MESSAGE = (
    "Ingestion was interrupted by a server restart. "
    "Any partial files were cleaned up; remove this entry and add it again."
)


def recover_interrupted_jobs(db_path, repos_dir=None, uploads_dir=None) -> int:
    """Fail jobs left mid-flight by a previous process, and return how many.

    Worker threads are daemons: if the process dies (crash, reloader restart,
    Ctrl+C), rows can stay ``pending``/``running`` forever with nobody left to
    finish them. Called once at startup. A repo whose task had already reached
    ``ready`` is left untouched; one that never got there is marked failed.

    When runtime directories are provided, partial repo dirs and staged upload
    zips are removed with strict path guards. Only ``repos/<repo_id>`` and
    ``uploads/<repo_id>.zip`` are eligible, so a corrupt DB row cannot point
    cleanup at arbitrary files.
    """
    stale = db.query_all(
        db_path,
        "SELECT id, repo_id FROM ingest_jobs WHERE status IN (?, ?)",
        ACTIVE_STATUSES,
    )
    for row in stale:
        update_job(db_path, row["id"], status="failed", message=RECOVERY_MESSAGE)
        repo = registry.get_repo(db_path, row["repo_id"])
        if repo is not None and repo["status"] in ACTIVE_STATUSES:
            _cleanup_recovered_paths(repo, repos_dir, uploads_dir)
            registry.update_repo(
                db_path, row["repo_id"], status="failed", error=RECOVERY_MESSAGE
            )
    return len(stale)


def _cleanup_recovered_paths(repo: dict, repos_dir, uploads_dir) -> None:
    repo_id = repo["id"]
    if repos_dir is not None:
        try:
            root = Path(repos_dir).resolve()
            expected = (root / repo_id).resolve()
            registered = Path(repo["path"]).resolve() if repo.get("path") else expected
            if (
                registered == expected
                and expected != root
                and expected.is_relative_to(root)
            ):
                shutil.rmtree(expected, ignore_errors=True)
        except OSError:  # pragma: no cover — best-effort startup cleanup
            log.warning(
                "Could not clean interrupted repo directory for %s",
                repo_id,
                exc_info=True,
            )
    if uploads_dir is not None:
        try:
            root = Path(uploads_dir).resolve()
            staged = (root / f"{repo_id}.zip").resolve()
            if staged != root and staged.is_relative_to(root):
                staged.unlink(missing_ok=True)
        except OSError:  # pragma: no cover — best-effort startup cleanup
            log.warning(
                "Could not clean interrupted upload for %s", repo_id, exc_info=True
            )

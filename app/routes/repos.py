"""Repository registry API: ingest (zip upload / URL clone), list, detail, delete.

``POST /api/repos`` accepts either:

- multipart form data with a ``file`` field (a zip archive that includes
  ``.git``), or
- a JSON/form body with a ``url`` field (cloned as a full mirror).

Both forms start a background job and return ``202`` with the new repo and
job; the UI then polls ``GET /api/jobs/<id>`` or ``GET /api/repos``.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

from ..errors import ApiError
from ..services import ingest, jobs, metrics, registry

bp = Blueprint("repos", __name__, url_prefix="/api/repos")

_ACTIVE = ("pending", "running")


@bp.get("")
def list_repos():
    return jsonify({"repos": registry.list_repos(_db_path())})


@bp.post("")
def create_repo():
    config = current_app.config
    upload = request.files.get("file")
    has_file = upload is not None and bool(upload.filename)
    url_raw = _requested_url()

    if has_file and url_raw:
        raise ApiError(
            "Provide either a zip upload or a URL, not both.", 400, "invalid_request"
        )
    if not has_file and not url_raw:
        raise ApiError(
            "Provide a repository zip file or a remote URL.", 400, "invalid_request"
        )

    ctx = ingest.IngestContext.from_config(config)
    repo_id = jobs.new_id()
    repos_dir = Path(config["REPOS_DIR"])

    if has_file:
        try:
            staging = ingest.stage_upload(upload, ctx.uploads_dir, repo_id)
        except ingest.IngestError as exc:
            raise ApiError(str(exc), 400, exc.code) from exc
        registry.insert_repo(
            _db_path(),
            repo_id=repo_id,
            name=ingest.repo_name_from_filename(upload.filename),
            source_type="upload",
            source=upload.filename,
            path=repos_dir / repo_id,
        )
        job = jobs.create_job(_db_path(), repo_id, kind="upload")
        jobs.run_async(
            _db_path(),
            job["id"],
            repo_id,
            task=lambda reporter: ingest.run_upload_task(
                ctx, repo_id, staging, reporter
            ),
        )
    else:
        try:
            url = ingest.validate_url(url_raw)
        except ingest.IngestError as exc:
            raise ApiError(str(exc), 400, exc.code) from exc
        registry.insert_repo(
            _db_path(),
            repo_id=repo_id,
            name=ingest.repo_name_from_url(url),
            source_type="url",
            source=url,
            path=repos_dir / repo_id,
        )
        job = jobs.create_job(_db_path(), repo_id, kind="url")
        jobs.run_async(
            _db_path(),
            job["id"],
            repo_id,
            task=lambda reporter: ingest.run_clone_task(ctx, repo_id, url, reporter),
        )

    return (
        jsonify(
            {
                "repo": registry.get_repo(_db_path(), repo_id),
                "job": jobs.get_job(_db_path(), job["id"]),
            }
        ),
        202,
    )


@bp.get("/<repo_id>")
def get_repo(repo_id: str):
    repo = registry.get_repo(_db_path(), repo_id)
    if repo is None:
        raise ApiError("Repository not found.", 404, "not_found")
    return jsonify({"repo": repo})


@bp.delete("/<repo_id>")
def delete_repo(repo_id: str):
    repo = registry.get_repo(_db_path(), repo_id)
    if repo is None:
        raise ApiError("Repository not found.", 404, "not_found")
    if repo["status"] in _ACTIVE:
        raise ApiError(
            "This repository is still ingesting — wait for the job to finish first.",
            409,
            "busy",
        )
    _remove_repo_dir(repo_id)
    registry.delete_repo(_db_path(), repo_id)
    metrics.invalidate(repo_id)
    return "", 204


def _requested_url() -> str:
    url = (request.form.get("url") or "").strip()
    if url:
        return url
    if request.is_json:
        payload = request.get_json(silent=True)
        if isinstance(payload, dict):
            return str(payload.get("url") or "").strip()
    return ""


def _remove_repo_dir(repo_id: str) -> None:
    """Delete ``instance/repos/<id>`` (guarded to stay inside REPOS_DIR)."""
    repos_root = Path(current_app.config["REPOS_DIR"]).resolve()
    target = (repos_root / repo_id).resolve()
    if target != repos_root and target.is_relative_to(repos_root) and target.exists():
        shutil.rmtree(target, ignore_errors=True)


def _db_path():
    return current_app.config["DATABASE_PATH"]

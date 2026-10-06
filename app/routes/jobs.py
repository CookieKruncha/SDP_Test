"""Ingest job status API (polled by the UI for progress and outcomes)."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify

from ..errors import ApiError
from ..services import jobs

bp = Blueprint("jobs", __name__, url_prefix="/api/jobs")


@bp.get("/<job_id>")
def get_job(job_id: str):
    job = jobs.get_job(current_app.config["DATABASE_PATH"], job_id)
    if job is None:
        raise ApiError("Job not found.", 404, "not_found")
    return jsonify({"job": job})

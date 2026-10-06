"""Metrics API: file / directory / repository / author metrics for one
ingested repository (commit set = all non-merge commits reachable from the
stored HEAD, i.e. H-bar from the brief).
"""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify

from ..errors import ApiError
from ..services import metrics, registry

bp = Blueprint("metrics", __name__, url_prefix="/api/repos")


@bp.get("/<repo_id>/metrics")
def get_metrics(repo_id: str):
    repo = registry.get_repo(current_app.config["DATABASE_PATH"], repo_id)
    if repo is None:
        raise ApiError("Repository not found.", 404, "not_found")
    if repo["status"] != "ready":
        raise ApiError(
            "This repository has not finished ingesting yet.", 409, "not_ready"
        )

    result = metrics.get_analysis(repo_id, repo["path"], repo["head_sha"])
    payload = metrics.to_json(result)
    payload["repo_id"] = repo_id
    payload["head_sha"] = repo["head_sha"]
    return jsonify(payload)

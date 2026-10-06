"""Metrics API: file / directory / repository / author metrics for one
ingested repository, filterable by author, committer-date window, or an
explicit commit SHA list -- the commit-set filters from the brief (H_t,
H_i,j, manual list) and the authorship test for the author filter.
"""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from ..errors import ApiError
from ..services import authors, metrics, registry

bp = Blueprint("metrics", __name__, url_prefix="/api/repos")


@bp.get("/<repo_id>/metrics")
def get_metrics(repo_id: str):
    repo = _ready_repo(repo_id)
    db_path = current_app.config["DATABASE_PATH"]
    alias_map = authors.get_alias_map(db_path, repo_id)
    since, until = _parse_window()

    result = metrics.get_analysis(
        repo_id,
        repo["path"],
        repo["head_sha"],
        raw_authors=_raw_authors_for(request.args.get("author"), alias_map),
        since=since,
        until=until,
        shas=_parse_shas(),
    )

    payload = metrics.to_json(result, alias_map)
    payload["repo_id"] = repo_id
    payload["head_sha"] = repo["head_sha"]
    return jsonify(payload)


@bp.get("/<repo_id>/authors")
def list_authors(repo_id: str):
    repo = _ready_repo(repo_id)
    db_path = current_app.config["DATABASE_PATH"]
    result = metrics.get_analysis(repo_id, repo["path"], repo["head_sha"])
    groups = authors.list_groups(db_path, repo_id, result.authors)
    return jsonify({"groups": groups})


@bp.post("/<repo_id>/authors/merge")
def merge_authors(repo_id: str):
    body = request.get_json(silent=True) or {}
    raw_authors = body.get("authors")
    canonical = (body.get("canonical") or "").strip()
    if not isinstance(raw_authors, list) or not raw_authors or not canonical:
        raise ApiError(
            "Provide 'authors' (a non-empty list) and a non-empty 'canonical' name.",
            400,
            "invalid_request",
        )
    return _apply_alias_change(
        repo_id, lambda db_path: authors.merge_authors(db_path, repo_id, raw_authors, canonical)
    )


@bp.post("/<repo_id>/authors/split")
def split_author(repo_id: str):
    body = request.get_json(silent=True) or {}
    raw_author = (body.get("author") or "").strip()
    if not raw_author:
        raise ApiError("Provide the 'author' to split out.", 400, "invalid_request")
    return _apply_alias_change(
        repo_id, lambda db_path: authors.split_author(db_path, repo_id, raw_author)
    )


def _apply_alias_change(repo_id: str, mutate):
    """Run an alias-table mutation, then return the refreshed author groups.

    The alias table only affects display grouping (``to_json``), not the
    underlying commit stream, so invalidating the metrics cache here is not
    strictly required for correctness -- it's done anyway since it's cheap
    and keeps a single mental model (every alias change starts clean).
    """
    repo = _ready_repo(repo_id)
    db_path = current_app.config["DATABASE_PATH"]
    mutate(db_path)
    metrics.invalidate(repo_id)
    result = metrics.get_analysis(repo_id, repo["path"], repo["head_sha"])
    groups = authors.list_groups(db_path, repo_id, result.authors)
    return jsonify({"groups": groups})


def _raw_authors_for(author_param, alias_map) -> frozenset | None:
    """Expand a requested (possibly merged/canonical) author name back to the
    set of raw mailmap authors it covers.
    """
    if not author_param:
        return None
    members = [raw for raw, canon in alias_map.items() if canon == author_param]
    return frozenset(members) if members else frozenset({author_param})


def _ready_repo(repo_id: str) -> dict:
    repo = registry.get_repo(current_app.config["DATABASE_PATH"], repo_id)
    if repo is None:
        raise ApiError("Repository not found.", 404, "not_found")
    if repo["status"] != "ready":
        raise ApiError(
            "This repository has not finished ingesting yet.", 409, "not_ready"
        )
    return repo


def _parse_window() -> tuple:
    since = request.args.get("since", type=int)
    until = request.args.get("until", type=int)
    return since, until


def _parse_shas() -> frozenset | None:
    raw = request.args.get("commits")
    if not raw:
        return None
    return frozenset(s.strip() for s in raw.split(",") if s.strip())

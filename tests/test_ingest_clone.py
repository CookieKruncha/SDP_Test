"""URL-clone ingestion: source validation (sync) and mirror-clone outcomes."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.services import ingest

from helpers import make_bare_clone, wait_for_job, wait_for_repo


def _post_url(client, url: str):
    return client.post("/api/repos", json={"url": url})


def test_clone_from_local_path_becomes_ready(client, app, fixture_repo, tmp_path):
    origin = make_bare_clone(fixture_repo.path, tmp_path / "origin.git")
    resp = _post_url(client, str(origin))
    assert resp.status_code == 202, resp.get_data(as_text=True)
    payload = resp.get_json()

    job = wait_for_job(client, payload["job"]["id"])
    assert job["status"] == "done", job["message"]

    repo = wait_for_repo(client, payload["repo"]["id"])
    assert repo["status"] == "ready"
    assert repo["source_type"] == "url"
    assert repo["source"] == str(origin)
    assert repo["name"] == "origin"
    assert repo["head_sha"] == fixture_repo.rev("merge feature")
    assert repo["commit_count"] == 10
    assert repo["non_merge_count"] == 9
    assert Path(repo["path"]).is_relative_to(Path(app.config["REPOS_DIR"]))


def test_clone_from_file_url_becomes_ready(client, fixture_repo, tmp_path):
    origin = make_bare_clone(fixture_repo.path, tmp_path / "origin.git")
    resp = _post_url(client, f"file://{origin}")
    assert resp.status_code == 202
    job = wait_for_job(client, resp.get_json()["job"]["id"])
    assert job["status"] == "done", job["message"]


def test_clone_failure_marks_repo_failed_and_cleans_up(client, app, tmp_path):
    resp = _post_url(client, f"file://{tmp_path}/missing.git")
    assert resp.status_code == 202
    payload = resp.get_json()

    job = wait_for_job(client, payload["job"]["id"])
    assert job["status"] == "failed"
    assert "Clone failed" in job["message"]

    repo = wait_for_repo(client, payload["repo"]["id"])
    assert repo["status"] == "failed"
    assert repo["error"] == job["message"]
    # The partial clone directory is removed.
    assert not (Path(app.config["REPOS_DIR"]) / payload["repo"]["id"]).exists()


def test_clone_of_empty_repository_fails_friendly(client, tmp_path):
    empty_origin = tmp_path / "empty-origin.git"
    subprocess.run(
        ["git", "init", "--bare", str(empty_origin)], check=True, capture_output=True
    )
    resp = _post_url(client, str(empty_origin))
    assert resp.status_code == 202
    job = wait_for_job(client, resp.get_json()["job"]["id"])
    assert job["status"] == "failed"
    assert "no commits" in job["message"]


def test_invalid_scheme_rejected_synchronously(client):
    resp = _post_url(client, "ftp://example.com/repo.git")
    assert resp.status_code == 400
    body = resp.get_json()["error"]
    assert body["code"] == "invalid_url"
    assert "ftp" in body["message"]
    assert client.get("/api/repos").get_json()["repos"] == []


def test_garbage_url_rejected_synchronously(client):
    resp = _post_url(client, "just some text")
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "invalid_url"


def test_validate_url_accepts_common_forms():
    good = (
        "https://github.com/owner/repo.git",
        "http://host/repo",
        "ssh://git@host/owner/repo.git",
        "git://host/repo.git",
        "git@github.com:owner/repo.git",
        "file:///tmp/repo",
        "/abs/path/to/repo",
        "./relative/repo",
    )
    for url in good:
        assert ingest.validate_url(url) == url
    for bad in ("ftp://host/repo.git", "just text", "", "   ", "a" * 3000):
        with pytest.raises(ingest.IngestError):
            ingest.validate_url(bad)


def test_repo_name_derivation():
    assert (
        ingest.repo_name_from_url("https://github.com/DaveGamble/cJSON.git") == "cJSON"
    )
    assert ingest.repo_name_from_url("git@github.com:owner/repo.git") == "repo"
    assert ingest.repo_name_from_url("https://host/") == "host"
    assert ingest.repo_name_from_filename("my-repo.zip") == "my-repo"
    assert ingest.repo_name_from_filename("") == "upload"

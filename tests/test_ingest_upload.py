"""Zip-upload ingestion: validation, zip-slip safety, extraction, readiness."""

from __future__ import annotations

import shutil
from io import BytesIO
from pathlib import Path

from app.services import ingest

from helpers import (
    craft_zip,
    git,
    post_upload,
    wait_for_job,
    wait_for_repo,
    zip_directory,
)


def _ingest_ok(client, zip_path: Path):
    """Upload a zip and wait for the repo to become ready; return (repo, job)."""
    resp = post_upload(client, zip_path)
    assert resp.status_code == 202, resp.get_data(as_text=True)
    payload = resp.get_json()
    job = wait_for_job(client, payload["job"]["id"])
    assert job["status"] == "done", job["message"]
    repo = wait_for_repo(client, payload["repo"]["id"])
    return repo, job


def test_upload_fixture_zip_becomes_ready(client, app, fixture_repo, tmp_path):
    zip_path = zip_directory(fixture_repo.path, tmp_path / "upload.zip")
    repo, _ = _ingest_ok(client, zip_path)

    assert repo["status"] == "ready"
    assert repo["source_type"] == "upload"
    assert repo["name"] == "upload"
    assert repo["error"] is None
    assert repo["head_sha"] == fixture_repo.rev("merge feature")
    assert repo["commit_count"] == 10
    assert repo["non_merge_count"] == 9

    # The registered path is the extracted repo, usable by plain git.
    assert Path(repo["path"]).is_relative_to(Path(app.config["REPOS_DIR"]))
    assert git(repo["path"], "rev-parse", "HEAD") == repo["head_sha"]

    # The staged upload is cleaned up after the job.
    assert list(Path(app.config["UPLOADS_DIR"]).iterdir()) == []


def test_upload_wrapped_folder_is_unwrapped(client, fixture_repo, tmp_path):
    zip_path = zip_directory(
        fixture_repo.path, tmp_path / "wrapped.zip", arcprefix="myrepo/"
    )
    repo, _ = _ingest_ok(client, zip_path)
    assert repo["status"] == "ready"
    assert Path(repo["path"]).name == "myrepo"
    assert repo["non_merge_count"] == 9


def test_upload_supports_git_file_pointer(client, fixture_repo, tmp_path):
    """A zip whose .git is a file pointing at an in-tree gitdir stays usable."""
    work = tmp_path / "work"
    repo_dir = work / "repo"
    shutil.copytree(fixture_repo.path, repo_dir)
    gitdir = work / "gitstore"
    (repo_dir / ".git").rename(gitdir)
    (repo_dir / ".git").write_text("gitdir: ../gitstore\n")

    zip_path = zip_directory(work, tmp_path / "gitfile.zip")
    repo, _ = _ingest_ok(client, zip_path)
    assert repo["status"] == "ready"
    assert Path(repo["path"]).name == "repo"
    assert repo["head_sha"] == fixture_repo.rev("merge feature")


def test_upload_rejects_non_zip(client, app):
    resp = client.post(
        "/api/repos",
        data={"file": (BytesIO(b"definitely not a zip"), "notes.zip")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "invalid_zip"
    assert client.get("/api/repos").get_json()["repos"] == []
    assert list(Path(app.config["UPLOADS_DIR"]).iterdir()) == []


def test_upload_rejects_empty_zip(client, tmp_path):
    zip_path = craft_zip(tmp_path / "empty.zip", {})
    resp = post_upload(client, zip_path)
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "invalid_zip"


def test_upload_rejects_zip_without_git(client, tmp_path):
    src = tmp_path / "plain"
    (src / "docs").mkdir(parents=True)
    (src / "docs" / "readme.txt").write_text("hello")
    zip_path = zip_directory(src, tmp_path / "plain.zip")
    resp = post_upload(client, zip_path)
    assert resp.status_code == 400
    body = resp.get_json()["error"]
    assert body["code"] == "missing_git"
    assert ".git" in body["message"]


def test_upload_rejects_zip_slip(client, app, tmp_path):
    zip_path = craft_zip(
        tmp_path / "evil.zip",
        {"../evil.txt": b"pwned", ".git/HEAD": b"ref: refs/heads/main\n"},
    )
    resp = post_upload(client, zip_path)
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "unsafe_archive"
    # Nothing was written outside the staging area, and no repo row exists.
    assert not (tmp_path / "evil.txt").exists()
    assert client.get("/api/repos").get_json()["repos"] == []


def test_upload_rejects_absolute_paths(client, tmp_path):
    zip_path = craft_zip(tmp_path / "abs.zip", {"/abs.txt": b"x"})
    resp = post_upload(client, zip_path)
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "unsafe_archive"


def test_filesystem_error_marks_repo_and_job_failed(
    client, fixture_repo, tmp_path, monkeypatch
):
    zip_path = zip_directory(fixture_repo.path, tmp_path / "upload.zip")

    def boom(zip_path, dest_dir, reporter):
        raise OSError("No space left on device")

    monkeypatch.setattr(ingest, "extract_zip", boom)
    resp = post_upload(client, zip_path)
    payload = resp.get_json()

    job = wait_for_job(client, payload["job"]["id"])
    assert job["status"] == "failed"
    assert "No space left on device" in job["message"]

    repo = wait_for_repo(client, payload["repo"]["id"])
    assert repo["status"] == "failed"
    assert "No space left on device" in repo["error"]

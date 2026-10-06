"""Registry API: list/detail/delete semantics, job lifecycle, request validation."""

from __future__ import annotations

import subprocess
import threading
from io import BytesIO
from pathlib import Path

from app import create_app
from app.services import ingest, jobs, registry

from helpers import post_upload, wait_for_job, zip_directory


def test_repo_list_is_empty_initially(client):
    assert client.get("/api/repos").get_json() == {"repos": []}


def test_repo_detail_unknown_returns_json_404(client):
    resp = client.get("/api/repos/nope")
    assert resp.status_code == 404
    assert resp.get_json()["error"]["code"] == "not_found"


def test_job_unknown_returns_json_404(client):
    resp = client.get("/api/jobs/nope")
    assert resp.status_code == 404
    assert resp.get_json()["error"]["code"] == "not_found"


def test_job_reports_progress_and_finishes(client, fixture_repo, tmp_path):
    zip_path = zip_directory(fixture_repo.path, tmp_path / "upload.zip")
    resp = post_upload(client, zip_path)
    payload = resp.get_json()
    job_id = payload["job"]["id"]

    job = client.get(f"/api/jobs/{job_id}").get_json()["job"]
    assert job["status"] in ("pending", "running", "done")
    assert job["kind"] == "upload"
    assert job["repo_id"] == payload["repo"]["id"]
    assert isinstance(job["progress"], float)

    final = wait_for_job(client, job_id)
    assert final["status"] == "done"
    assert final["progress"] == 1.0
    assert final["phase"] == "finished"


def test_repo_list_shows_latest_job_progress(client, fixture_repo, tmp_path):
    zip_path = zip_directory(fixture_repo.path, tmp_path / "upload.zip")
    payload = post_upload(client, zip_path).get_json()
    wait_for_job(client, payload["job"]["id"])

    repos = client.get("/api/repos").get_json()["repos"]
    assert len(repos) == 1
    repo = repos[0]
    assert repo["id"] == payload["repo"]["id"]
    assert repo["job"]["id"] == payload["job"]["id"]
    assert repo["job"]["status"] == "done"
    assert repo["job"]["progress"] == 1.0


def test_delete_removes_row_files_and_job_history(client, app, fixture_repo, tmp_path):
    zip_path = zip_directory(fixture_repo.path, tmp_path / "upload.zip")
    payload = post_upload(client, zip_path).get_json()
    repo_id = payload["repo"]["id"]
    job_id = payload["job"]["id"]
    wait_for_job(client, job_id)

    repo_dir = Path(app.config["REPOS_DIR"]) / repo_id
    assert repo_dir.exists()

    resp = client.delete(f"/api/repos/{repo_id}")
    assert resp.status_code == 204
    assert client.get(f"/api/repos/{repo_id}").status_code == 404
    assert client.get("/api/repos").get_json()["repos"] == []
    assert not repo_dir.exists()
    # The job row is cascaded away with its repo.
    assert client.get(f"/api/jobs/{job_id}").status_code == 404


def test_delete_missing_returns_404(client):
    assert client.delete("/api/repos/nope").status_code == 404


def test_delete_conflicts_while_ingesting(client, fixture_repo, tmp_path, monkeypatch):
    gate = threading.Event()
    original_extract = ingest.extract_zip

    def gated(zip_path, dest_dir, reporter):
        gate.wait(timeout=15)
        return original_extract(zip_path, dest_dir, reporter)

    monkeypatch.setattr(ingest, "extract_zip", gated)
    zip_path = zip_directory(fixture_repo.path, tmp_path / "upload.zip")
    payload = post_upload(client, zip_path).get_json()
    try:
        resp = client.delete(f"/api/repos/{payload['repo']['id']}")
        assert resp.status_code == 409
        assert resp.get_json()["error"]["code"] == "busy"
    finally:
        gate.set()
    wait_for_job(client, payload["job"]["id"])


def test_post_requires_a_source(client):
    resp = client.post("/api/repos", json={})
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "invalid_request"


def test_post_rejects_file_and_url_together(client, app, fixture_repo, tmp_path):
    zip_path = zip_directory(fixture_repo.path, tmp_path / "upload.zip")
    resp = client.post(
        "/api/repos",
        data={
            "file": (BytesIO(zip_path.read_bytes()), "upload.zip"),
            "url": "https://github.com/owner/repo.git",
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "invalid_request"
    assert list(Path(app.config["UPLOADS_DIR"]).iterdir()) == []
    assert client.get("/api/repos").get_json()["repos"] == []


def test_post_accepts_form_encoded_url(client, fixture_repo, tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(
        ["git", "clone", "--bare", str(fixture_repo.path), str(origin)],
        check=True,
        capture_output=True,
    )
    resp = client.post("/api/repos", data={"url": str(origin)})
    assert resp.status_code == 202
    job = wait_for_job(client, resp.get_json()["job"]["id"])
    assert job["status"] == "done", job["message"]


def test_recover_interrupted_jobs_fails_stale_rows_and_cleans_files(app):
    db_path = app.config["DATABASE_PATH"]
    repo_dir = Path(app.config["REPOS_DIR"]) / "stale-repo"
    repo_dir.mkdir(parents=True)
    (repo_dir / "partial.txt").write_text("incomplete")
    upload_zip = Path(app.config["UPLOADS_DIR"]) / "stale-repo.zip"
    upload_zip.write_bytes(b"partial upload")
    repo_id = registry.insert_repo(
        db_path,
        repo_id="stale-repo",
        name="stale",
        source_type="url",
        source="https://example.com/stale.git",
        path=repo_dir,
    )["id"]
    running_id = jobs.create_job(db_path, repo_id, "clone")["id"]
    jobs.update_job(
        db_path, running_id, status="running", phase="cloning", progress=0.4
    )
    pending_id = jobs.create_job(db_path, repo_id, "upload")["id"]
    done_id = jobs.create_job(db_path, repo_id, "clone")["id"]
    jobs.update_job(db_path, done_id, status="done", phase="finished", progress=1.0)

    assert (
        jobs.recover_interrupted_jobs(
            db_path, app.config["REPOS_DIR"], app.config["UPLOADS_DIR"]
        )
        == 2
    )
    assert (
        jobs.recover_interrupted_jobs(
            db_path, app.config["REPOS_DIR"], app.config["UPLOADS_DIR"]
        )
        == 0
    )  # idempotent

    for job_id in (running_id, pending_id):
        job = jobs.get_job(db_path, job_id)
        assert job["status"] == "failed"
        assert "interrupted" in job["message"].lower()
    assert jobs.get_job(db_path, done_id)["status"] == "done"

    repo = registry.get_repo(db_path, repo_id)
    assert repo["status"] == "failed"
    assert "partial files were cleaned up" in repo["error"].lower()
    assert not repo_dir.exists()
    assert not upload_zip.exists()


def test_app_creation_recovers_jobs_left_running(app):
    """A restart (fresh create_app on the same DB) must unstick old rows."""
    db_path = app.config["DATABASE_PATH"]
    repo_dir = Path(app.config["REPOS_DIR"]) / "interrupted-repo"
    repo_dir.mkdir(parents=True)
    (repo_dir / "partial.txt").write_text("incomplete")
    repo_id = registry.insert_repo(
        db_path,
        repo_id="interrupted-repo",
        name="interrupted",
        source_type="upload",
        source="demo.zip",
        path=repo_dir,
    )["id"]
    job_id = jobs.create_job(db_path, repo_id, "upload")["id"]
    jobs.update_job(db_path, job_id, status="running", phase="validating", progress=1.0)

    create_app(
        INSTANCE_DIR=app.config["INSTANCE_DIR"],
        REPOS_DIR=app.config["REPOS_DIR"],
        UPLOADS_DIR=app.config["UPLOADS_DIR"],
        DATABASE_PATH=db_path,
        TESTING=True,
    )

    assert jobs.get_job(db_path, job_id)["status"] == "failed"
    assert registry.get_repo(db_path, repo_id)["status"] == "failed"
    assert not repo_dir.exists()


def test_oversized_upload_returns_friendly_json(tmp_path):
    oversized_app = create_app(
        INSTANCE_DIR=tmp_path / "instance",
        REPOS_DIR=tmp_path / "instance" / "repos",
        UPLOADS_DIR=tmp_path / "instance" / "uploads",
        DATABASE_PATH=tmp_path / "instance" / "rat.db",
        MAX_CONTENT_LENGTH=64,
        TESTING=True,
    )
    resp = oversized_app.test_client().post(
        "/api/repos",
        data={"file": (BytesIO(b"x" * 512), "too-big.zip")},
        content_type="multipart/form-data",
    )

    assert resp.status_code == 413
    assert resp.get_json() == {
        "error": {
            "code": "upload_too_large",
            "message": "The uploaded file is too large (64 bytes max). Upload a smaller zip archive.",
        }
    }

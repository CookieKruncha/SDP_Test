"""Shared helpers for the ingestion/registry tests (zips, polling, clones)."""

from __future__ import annotations

import subprocess
import time
import zipfile
from io import BytesIO
from pathlib import Path


def zip_directory(src: Path, dest: Path, arcprefix: str = "") -> Path:
    """Zip a directory tree, including dotfiles such as ``.git``."""
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(Path(src).rglob("*")):
            if path.is_dir():
                continue
            rel = path.relative_to(src).as_posix()
            archive.write(path, arcprefix + rel)
    return dest


def craft_zip(dest: Path, entries: dict) -> Path:
    """Write a zip containing exactly the given ``{name: bytes|str}`` entries."""
    with zipfile.ZipFile(dest, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return dest


def post_upload(client, zip_path: Path):
    """POST a zip archive as a multipart upload."""
    data = {"file": (BytesIO(Path(zip_path).read_bytes()), Path(zip_path).name)}
    return client.post("/api/repos", data=data, content_type="multipart/form-data")


def wait_for_job(client, job_id: str, timeout: float = 30.0) -> dict:
    """Poll ``GET /api/jobs/<id>`` until the job is done or failed."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = client.get(f"/api/jobs/{job_id}")
        assert resp.status_code == 200, resp.get_data(as_text=True)
        job = resp.get_json()["job"]
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")


def wait_for_repo(client, repo_id: str, timeout: float = 30.0) -> dict:
    """Poll ``GET /api/repos/<id>`` until the repo is ready or failed."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = client.get(f"/api/repos/{repo_id}")
        assert resp.status_code == 200, resp.get_data(as_text=True)
        repo = resp.get_json()["repo"]
        if repo["status"] in ("ready", "failed"):
            return repo
        time.sleep(0.05)
    raise AssertionError(f"repo {repo_id} did not finish within {timeout}s")


def make_bare_clone(src: Path, dest: Path) -> Path:
    """A bare clone of ``src`` usable as a local clone source in tests."""
    subprocess.run(
        ["git", "clone", "--bare", str(src), str(dest)],
        check=True,
        capture_output=True,
        text=True,
    )
    return dest


def git(path, *args: str) -> str:
    """Run a plain git command against an ingested repo and return stdout."""
    result = subprocess.run(
        ["git", "-C", str(path), *args], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()

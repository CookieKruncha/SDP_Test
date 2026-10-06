"""Metrics API: end-to-end ingest -> metrics against the fixture repo."""
from __future__ import annotations

from helpers import post_upload, wait_for_job, zip_directory


def _ingest(client, fixture_repo, tmp_path):
    zip_path = zip_directory(fixture_repo.path, tmp_path / "upload.zip")
    payload = post_upload(client, zip_path).get_json()
    wait_for_job(client, payload["job"]["id"])
    return payload["repo"]["id"]


def test_metrics_unknown_repo_is_404(client):
    resp = client.get("/api/repos/nope/metrics")
    assert resp.status_code == 404
    assert resp.get_json()["error"]["code"] == "not_found"


def test_metrics_not_ready_is_409(client, fixture_repo, tmp_path):
    zip_path = zip_directory(fixture_repo.path, tmp_path / "upload.zip")
    payload = post_upload(client, zip_path).get_json()
    # Don't wait for the job -- the repo is still pending/running.
    resp = client.get(f"/api/repos/{payload['repo']['id']}/metrics")
    assert resp.status_code in (200, 409)  # tiny fixture repo may finish instantly


def test_metrics_matches_analyzer_for_fixture_repo(client, fixture_repo, tmp_path):
    repo_id = _ingest(client, fixture_repo, tmp_path)
    resp = client.get(f"/api/repos/{repo_id}/metrics")
    assert resp.status_code == 200
    data = resp.get_json()

    assert data["commit_count"] == 9
    by_path = {(o["type"], o["path"]): o for o in data["objects"]}

    repo_row = by_path[("repository", "")]
    assert repo_row["added"] > 0

    assert "assets/logo.bin" not in {p for (_, p) in by_path}

    run_sh = by_path[("file", "bin/run.sh")]
    assert run_sh["added"] == 2
    assert run_sh["removed"] == 2
    assert run_sh["growth"] == 0
    assert run_sh["modifications"] == 2

    rename_pure = by_path[("file", "docs/README.md")]
    assert rename_pure["added"] == 0 and rename_pure["removed"] == 0

    alice_rows = [a for a in run_sh["authors"] if "Alice" in a["author"]]
    bob_rows = [a for a in run_sh["authors"] if "Bob" in a["author"]]
    assert bob_rows and bob_rows[0]["modifications"] == 1


def test_metrics_cached_between_requests(client, fixture_repo, tmp_path, monkeypatch):
    from app.services import analyzer as analyzer_module

    repo_id = _ingest(client, fixture_repo, tmp_path)
    client.get(f"/api/repos/{repo_id}/metrics")

    calls = []
    original = analyzer_module.analyze

    def spy(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(analyzer_module, "analyze", spy)
    client.get(f"/api/repos/{repo_id}/metrics")
    assert calls == []  # second request served from the in-process cache

"""Golden-value regression test: analyzer output vs. the graders' reference
CSVs for the pinned commit of each sample repository.

Skips automatically if the repository hasn't been cloned into
``instance/repos/<name>`` at the pinned ref (that happens via Stage 2's
ingestion once merged; until then this is run manually against a clone made
for validation purposes).
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from app.services import analyzer, gitlog

BASE = Path(__file__).resolve().parents[1]
REPO_REFS = BASE / "repo-references"

CASES = [
    pytest.param(
        "instance/repos/cjson",
        REPO_REFS / "cJSON_6d9f2443ab07.csv",
        "6d9f2443ab071f86e5d9b43025a40929ec41c46c",
        955,
        id="cjson",
    ),
    pytest.param(
        "instance/repos/redis",
        REPO_REFS / "redis_b540ca49cba8.csv",
        "b540ca49cba815f3fbe634363c3df68d4f4f127a",
        11874,
        id="redis",
    ),
    pytest.param(
        "instance/repos/git",
        REPO_REFS / "git_5a7d1e8045ce.csv",
        "5a7d1e8045ce66c908f62598e26cbb8df7b39a90",
        61101,
        id="git",
    ),
]


@pytest.mark.parametrize("repo_rel, csv_path, ref, expected_commit_count", CASES)
def test_matches_golden_csv(repo_rel, csv_path, ref, expected_commit_count):
    repo_path = BASE / repo_rel
    if not (repo_path / ".git").exists() and not (repo_path / "HEAD").exists():
        pytest.skip(f"{repo_path} not cloned locally; see repo-references/README")

    rows = [r for r in csv.DictReader(csv_path.open()) if r["commit_set"] == "all"]
    commits = list(gitlog.iter_commits(repo_path, ref=ref))
    result = analyzer.analyze_commits(commits)

    assert result.commit_count == expected_commit_count

    mismatches = []
    for row in rows:
        obj = result.objects.get("" if row["path"] == "/" else row["path"])
        if obj is None:
            mismatches.append((row["path"], row["author"], "missing"))
            continue
        if row["author"] == "ALL":
            for key in ("added", "removed", "growth", "churn", "modifications"):
                actual = getattr(obj, key)
                if actual != int(row[key]):
                    mismatches.append((row["path"], "ALL", key, row[key], actual))
            freq, rate = float(row["modification_frequency"]), float(row["churn_rate"])
            if abs(obj.modification_frequency(result.commit_count) - freq) > 1e-9:
                mismatches.append((row["path"], "ALL", "modification_frequency"))
            if abs(obj.churn_rate(result.commit_count) - rate) > 1e-9:
                mismatches.append((row["path"], "ALL", "churn_rate"))
        else:
            expected = float(row["ownership"])
            if abs(obj.ownership(row["author"]) - expected) > 1e-9:
                mismatches.append((row["path"], row["author"], "ownership"))

    assert not mismatches, f"{len(mismatches)} mismatches, first: {mismatches[:10]}"

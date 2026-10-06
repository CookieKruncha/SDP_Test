"""On-demand metric computation for ingested repositories.

Caches the raw (already mailmap-resolved) commit stream per
``(repo_id, head_sha)`` -- re-ingesting a repo at a new ref naturally
invalidates it -- and layers filtering (commit-set + author) on top,
re-aggregating with ``analyzer.analyze_commits`` for each distinct filter
combination requested. Analysis results per filter signature are cached
too, so repeated identical requests (the common case while a user adjusts
one filter at a time) are free.

This on-demand approach is a pragmatic stand-in for Stage 9's SQLite-backed
precompute: correct and fine up to the "medium" (~10k commit) tier, but a
cache miss still re-walks history, which will not hold at ~100k commits.
"""
from __future__ import annotations

from . import analyzer, gitlog

_commits_cache: dict[tuple[str, str], list] = {}
_analysis_cache: dict[tuple, analyzer.AnalysisResult] = {}


def get_commits(repo_id: str, repo_path, head_sha: str) -> list:
    key = (repo_id, head_sha)
    commits = _commits_cache.get(key)
    if commits is None:
        commits = list(gitlog.iter_commits(repo_path, ref=head_sha))
        _commits_cache[key] = commits
    return commits


def get_analysis(
    repo_id: str,
    repo_path,
    head_sha: str,
    *,
    raw_authors: frozenset | None = None,
    since: int | None = None,
    until: int | None = None,
    shas: frozenset | None = None,
) -> analyzer.AnalysisResult:
    """Compute metrics over a filtered commit set H (brief sections H_t,
    H_i,j, and the authorship test). ``raw_authors`` is the set of raw
    mailmap-resolved author strings to keep (already expanded from any
    manually merged canonical name by the caller).
    """
    sig = (repo_id, head_sha, raw_authors, since, until, shas)
    result = _analysis_cache.get(sig)
    if result is not None:
        return result

    commits = get_commits(repo_id, repo_path, head_sha)
    if raw_authors is not None or since is not None or until is not None or shas is not None:
        commits = [
            c
            for c in commits
            if (raw_authors is None or c.author in raw_authors)
            and (since is None or c.committer_date >= since)
            and (until is None or c.committer_date < until)
            and (shas is None or c.sha in shas)
        ]
    result = analyzer.analyze_commits(commits)
    _analysis_cache[sig] = result
    return result


def invalidate(repo_id: str) -> None:
    """Drop every cached entry for a repo (call on delete/re-ingest)."""
    for cache in (_commits_cache, _analysis_cache):
        for key in [k for k in cache if k[0] == repo_id]:
            del cache[key]


def to_json(result: analyzer.AnalysisResult, alias_map: dict[str, str] | None = None) -> dict:
    """Shape an :class:`AnalysisResult` into the API's object list, mirroring
    the brief's categories: repository (root), directory, file -- each with
    nested per-author rows. ``alias_map`` (raw mailmap author -> manually
    merged canonical name) is applied here by grouping and summing author
    contributions before computing ownership, since ownership is not
    additive on its own (it's a ratio).
    """
    alias_map = alias_map or {}
    objects = []
    for obj in result.objects.values():
        merged: dict[str, dict] = {}
        for raw in set(obj.author_added) | set(obj.author_removed):
            canonical = alias_map.get(raw, raw)
            bucket = merged.setdefault(canonical, {"added": 0, "removed": 0, "modifications": 0})
            bucket["added"] += obj.author_added.get(raw, 0)
            bucket["removed"] += obj.author_removed.get(raw, 0)
            bucket["modifications"] += obj.author_modifications.get(raw, 0)

        total_churn = obj.churn
        author_rows = [
            {
                "author": canonical,
                "added": v["added"],
                "removed": v["removed"],
                "growth": v["added"] - v["removed"],
                "churn": v["added"] + v["removed"],
                "modifications": v["modifications"],
                "ownership": (v["added"] + v["removed"]) / total_churn if total_churn else 0.0,
            }
            for canonical, v in sorted(merged.items())
        ]

        objects.append(
            {
                "path": obj.path,
                "type": "repository"
                if obj.path == ""
                else ("directory" if obj.is_dir else "file"),
                "added": obj.added,
                "removed": obj.removed,
                "growth": obj.growth,
                "churn": obj.churn,
                "modifications": obj.modifications,
                "modification_frequency": obj.modification_frequency(result.commit_count),
                "churn_rate": obj.churn_rate(result.commit_count),
                "authors": author_rows,
            }
        )
    objects.sort(key=lambda o: (o["type"] != "repository", o["type"] != "directory", o["path"]))
    merged_author_names = {alias_map.get(a, a) for a in result.authors}
    return {
        "commit_count": result.commit_count,
        "author_count": len(merged_author_names),
        "objects": objects,
    }

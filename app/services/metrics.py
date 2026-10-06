"""On-demand metric computation for ingested repositories, with a tiny
process-local cache so repeat requests for the same repo don't re-walk the
whole commit history.

Cache key is ``(repo_id, head_sha)``: a repo re-ingested at a new ref gets a
fresh cache entry automatically, no explicit invalidation needed. This is a
pragmatic stand-in for Stage 9's real SQLite-backed cache -- fine up to the
"medium" (~10k commit) performance tier, but every request still re-walks
history on a cache miss, which will not hold at ~100k commits.
"""
from __future__ import annotations

from . import analyzer

_cache: dict[tuple[str, str], analyzer.AnalysisResult] = {}


def get_analysis(repo_id: str, repo_path, head_sha: str) -> analyzer.AnalysisResult:
    key = (repo_id, head_sha)
    result = _cache.get(key)
    if result is None:
        result = analyzer.analyze(repo_path, ref=head_sha)
        _cache[key] = result
    return result


def invalidate(repo_id: str) -> None:
    """Drop any cached analysis for a repo (call on delete/re-ingest)."""
    for key in [k for k in _cache if k[0] == repo_id]:
        del _cache[key]


def to_json(result: analyzer.AnalysisResult) -> dict:
    """Shape an :class:`AnalysisResult` into the API's object list, mirroring
    the brief's categories: repository (root), directory, file -- each with
    nested per-author rows (added/removed/growth/churn/modifications/ownership).
    """
    objects = []
    for obj in result.objects.values():
        all_authors = sorted(set(obj.author_added) | set(obj.author_removed))
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
                "authors": [
                    {
                        "author": author,
                        "added": obj.author_added.get(author, 0),
                        "removed": obj.author_removed.get(author, 0),
                        "growth": obj.author_growth(author),
                        "churn": obj.author_churn(author),
                        "modifications": obj.author_modifications.get(author, 0),
                        "ownership": obj.ownership(author),
                    }
                    for author in all_authors
                ],
            }
        )
    objects.sort(key=lambda o: (o["type"] != "repository", o["type"] != "directory", o["path"]))
    return {
        "commit_count": result.commit_count,
        "author_count": len(result.authors),
        "objects": objects,
    }

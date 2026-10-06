"""Manual author merging: a per-repo alias table layered on top of git's
automatic ``.mailmap`` resolution (handled already in ``gitlog.py``).

Git merges identities that share a mailmap entry; this table additionally
lets a user merge arbitrary raw author strings under one canonical display
name when no mailmap is provided (or it's incomplete), per the brief:
"If no mailmap is provided, a user should still be able to merge different
authors manually."
"""
from __future__ import annotations

from .. import db


def get_alias_map(db_path, repo_id: str) -> dict[str, str]:
    """``{raw_author: canonical_author}`` for every merged author in a repo."""
    rows = db.query_all(
        db_path,
        "SELECT raw_author, canonical_author FROM author_aliases WHERE repo_id = ?",
        (repo_id,),
    )
    return {row["raw_author"]: row["canonical_author"] for row in rows}


def canonical_name(alias_map: dict[str, str], raw_author: str) -> str:
    return alias_map.get(raw_author, raw_author)


def merge_authors(db_path, repo_id: str, raw_authors: list[str], canonical: str) -> None:
    """Merge the given raw authors under ``canonical`` (upsert, idempotent)."""
    conn = db.connect(db_path)
    try:
        with conn:
            for raw in raw_authors:
                conn.execute(
                    "INSERT INTO author_aliases (repo_id, raw_author, canonical_author) "
                    "VALUES (?, ?, ?) "
                    "ON CONFLICT (repo_id, raw_author) DO UPDATE SET canonical_author = ?",
                    (repo_id, raw, canonical, canonical),
                )
    finally:
        conn.close()


def split_author(db_path, repo_id: str, raw_author: str) -> None:
    """Undo a merge for one raw author, reverting it to stand alone."""
    db.execute(
        db_path,
        "DELETE FROM author_aliases WHERE repo_id = ? AND raw_author = ?",
        (repo_id, raw_author),
    )


def list_groups(db_path, repo_id: str, raw_authors: set[str]) -> list[dict]:
    """Every raw author seen in the history, grouped by its current canonical
    name (authors not merged are their own single-member group).
    """
    alias_map = get_alias_map(db_path, repo_id)
    groups: dict[str, list[str]] = {}
    for raw in sorted(raw_authors):
        canonical = canonical_name(alias_map, raw)
        groups.setdefault(canonical, []).append(raw)
    return [
        {"canonical": canonical, "members": members}
        for canonical, members in sorted(groups.items())
    ]

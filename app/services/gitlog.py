"""Streams a repository's non-merge commit history via the ``git`` CLI.

Line counts, rename detection, binary detection, and author identity merging
are all delegated to git itself (``--numstat -M50%`` and mailmap-aware
``%aN``/``%aE``) so results match ``git log`` by construction instead of by
re-implementing diff semantics.

Output framing uses ASCII control characters as delimiters (``\\x1f`` field
separator, ``\\x1e`` record separator, ``\\x00`` NUL between numstat tokens)
because none of them can appear in a commit SHA, timestamp, or author name/
email, and ``-z`` already guards paths against embedded newlines.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

_FIELD_SEP = "\x1f"
_RECORD_SEP = "\x1e"
# A literal "COMMIT" + field separator prefixes every record so the raw
# stream can be split on that exact marker unambiguously in ``_parse``.
_FORMAT = "COMMIT" + _FIELD_SEP + _FIELD_SEP.join(["%H", "%P", "%ct", "%aN", "%aE"]) + _RECORD_SEP


@dataclass
class Change:
    """A single file's diff within one commit, already attributed to its
    post-rename path per the brief ("changes are attributed to its new path").
    """

    path: str
    added: int | None  # None for binary files (unmeasured)
    removed: int | None
    binary: bool
    old_path: str | None = None  # set when this entry is a rename/copy

    @property
    def is_rename(self) -> bool:
        return self.old_path is not None and self.old_path != self.path


@dataclass
class Commit:
    sha: str
    parent: str | None  # None for the initial commit (h[p] = h-empty)
    committer_date: int
    author: str  # mailmap-resolved "Name <email>", i.e. h[a] after merging
    changes: list[Change] = field(default_factory=list)


def iter_commits(repo_path, ref: str = "HEAD"):
    """Yield every non-merge commit reachable from ``ref``, newest first.

    Mirrors H-bar from the brief directly: ``--no-merges`` excludes merge
    commits, and ``-M50%`` enables the required rename threshold. Mailmap is
    read explicitly from ``HEAD:.mailmap`` so merging works the same whether
    the repository is a normal checkout or a bare mirror clone.
    """
    args = [
        "git",
        "-c",
        "mailmap.blob=HEAD:.mailmap",
        "log",
        ref,
        "--no-merges",
        "-M50%",
        "--numstat",
        "-z",
        f"--format={_FORMAT}",
    ]
    result = subprocess.run(
        args, cwd=str(repo_path), capture_output=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git log failed for {repo_path!s} @ {ref!s}: "
            f"{result.stderr.decode('utf-8', 'replace').strip()}"
        )
    yield from _parse(result.stdout)


def _parse(raw: bytes):
    marker = ("COMMIT" + _FIELD_SEP).encode()
    record_sep = _RECORD_SEP.encode()
    field_sep = _FIELD_SEP.encode()

    for chunk in raw.split(marker)[1:]:
        header, _, body = chunk.partition(record_sep)
        sha_b, parent_b, ct_b, name_b, email_b = header.split(field_sep)
        commit = Commit(
            sha=sha_b.decode(),
            parent=parent_b.decode() or None,
            committer_date=int(ct_b),
            author=f"{name_b.decode('utf-8', 'replace')} <{email_b.decode('utf-8', 'replace')}>",
        )
        # git emits a stray NUL + newline right after the record separator,
        # ahead of the first numstat token; strip it before splitting.
        commit.changes = list(_parse_changes(body.lstrip(b"\x00\n")))
        yield commit


def _parse_changes(body: bytes):
    if not body:
        return
    tokens = body.split(b"\x00")
    i = 0
    n = len(tokens)
    while i < n:
        token = tokens[i]
        if not token:
            i += 1
            continue
        added_b, removed_b, path_b = token.split(b"\t", 2)
        if path_b == b"":
            # Rename/copy: the two following tokens are old path, new path.
            old_path = tokens[i + 1].decode("utf-8", "replace")
            new_path = tokens[i + 2].decode("utf-8", "replace")
            i += 3
            path, old = new_path, old_path
        else:
            path = path_b.decode("utf-8", "replace")
            old = None
            i += 1
        binary = added_b == b"-" or removed_b == b"-"
        yield Change(
            path=path,
            added=None if binary else int(added_b),
            removed=None if binary else int(removed_b),
            binary=binary,
            old_path=old,
        )

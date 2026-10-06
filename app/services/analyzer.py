"""Computes file, directory, repository, commit-set, and author metrics from
a stream of :class:`~app.services.gitlog.Commit` records.

Terminology mirrors the brief directly:
  - object ``o``   -- a file or directory path; ``""`` is the repository root.
  - commit set ``H`` -- here always H-bar (all non-merge commits reachable
    from the ref), matching ``commit_set == "all"`` in the reference CSVs.
    Time-windowed/manual commit sets are a later stage; see the module
    docstring note below on why that is a safe, isolated extension point.

Binary files are excluded entirely (git cannot measure line counts on them,
and the brief states "Binary files are not measured"), so they never appear
as objects and never contribute to any directory/repository aggregate.

Design note on H[F]/H[D] for future windowed commit sets: the brief defines
``h[F]`` as the *full* file listing at a commit, not just the files touched
by it, so a windowed ``H[F]`` can include untouched-but-present files. The
"all" commit set used here coincides with "every path ever touched" because
every file's existence began with some add/rename event in H-bar, so no
extra tree-walking is needed. A windowed implementation will need to seed
the live file set from a tree snapshot at the window boundary.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import gitlog

ROOT = ""  # the repository root directory object, per "repository metrics
            # are directory metrics on the root of the commit tree"


@dataclass
class ObjectStats:
    """Commit-set metrics for one file or directory object."""

    path: str
    is_dir: bool
    added: int = 0  # l+_{H,o}
    removed: int = 0  # l-_{H,o}
    modifications: int = 0  # n_{H,o}
    author_added: dict = field(default_factory=dict)  # author -> int
    author_removed: dict = field(default_factory=dict)
    author_modifications: dict = field(default_factory=dict)

    @property
    def growth(self) -> int:  # delta_{H,o}
        return self.added - self.removed

    @property
    def churn(self) -> int:  # lambda_{H,o}
        return self.added + self.removed

    def modification_frequency(self, commit_count: int) -> float:  # eta
        return self.modifications / commit_count if commit_count else 0.0

    def churn_rate(self, commit_count: int) -> float:  # rho
        return self.churn / commit_count if commit_count else 0.0

    def author_growth(self, author: str) -> int:
        return self.author_added.get(author, 0) - self.author_removed.get(author, 0)

    def author_churn(self, author: str) -> int:
        return self.author_added.get(author, 0) + self.author_removed.get(author, 0)

    def ownership(self, author: str) -> float:  # omega_{H,o,a}
        total = self.churn
        if total == 0:
            return 0.0
        return self.author_churn(author) / total


@dataclass
class AnalysisResult:
    commit_count: int  # |H|
    objects: dict  # path -> ObjectStats (files and directories, "" = repo root)
    authors: set  # every author who contributed at least one non-binary change

    @property
    def repository(self) -> ObjectStats:
        return self.objects[ROOT]

    def files(self):
        return (o for o in self.objects.values() if not o.is_dir)

    def directories(self):
        return (o for o in self.objects.values() if o.is_dir)


def analyze(repo_path, ref: str = "HEAD") -> AnalysisResult:
    """Run the full metric computation for H-bar (all non-merge commits)."""
    return analyze_commits(gitlog.iter_commits(repo_path, ref=ref))


def analyze_commits(commits) -> AnalysisResult:
    """Same as :func:`analyze`, but over an already-materialised iterable of
    :class:`~app.services.gitlog.Commit` (keeps the fixture/golden tests fast
    and decoupled from spawning ``git`` for every assertion).
    """
    objects: dict[str, ObjectStats] = {ROOT: ObjectStats(path=ROOT, is_dir=True)}
    authors: set[str] = set()
    commit_count = 0

    for commit in commits:
        commit_count += 1
        authors.add(commit.author)
        # Per-commit totals keyed by object path, before folding into the
        # running commit-set totals -- needed so modification counts (n) are
        # incremented at most once per commit per object, even though a
        # directory can receive contributions from several files at once.
        per_commit: dict[str, tuple[int, int]] = {}
        for change in commit.changes:
            if change.binary:
                continue
            added, removed = change.added, change.removed
            for obj_path, is_dir in _object_and_ancestors(change.path):
                stats = objects.get(obj_path)
                if stats is None:
                    stats = objects[obj_path] = ObjectStats(path=obj_path, is_dir=is_dir)
                prev_added, prev_removed = per_commit.get(obj_path, (0, 0))
                per_commit[obj_path] = (prev_added + added, prev_removed + removed)

        for obj_path, (added, removed) in per_commit.items():
            stats = objects[obj_path]
            stats.added += added
            stats.removed += removed
            if added + removed > 0:
                stats.modifications += 1
                stats.author_added[commit.author] = (
                    stats.author_added.get(commit.author, 0) + added
                )
                stats.author_removed[commit.author] = (
                    stats.author_removed.get(commit.author, 0) + removed
                )
                stats.author_modifications[commit.author] = (
                    stats.author_modifications.get(commit.author, 0) + 1
                )

    return AnalysisResult(commit_count=commit_count, objects=objects, authors=authors)


def _object_and_ancestors(file_path: str):
    """Yield ``(path, is_dir)`` for the file itself, then every ancestor
    directory up to and including the repository root.

    A directory's metrics are the sum of its immediate children's metrics
    (recursively), which by associativity is equivalent to summing directly
    over every descendant file -- so a single file's change is simply added,
    unsplit, to the file object and to each of its ancestor directories.
    """
    yield file_path, False
    parts = file_path.split("/")[:-1]
    for depth in range(len(parts), 0, -1):
        yield "/".join(parts[:depth]), True
    yield ROOT, True

"""Fixture-repo tests for the commit-stream analyzer.

Uses ``tests/conftest.py``'s ``build_fixture_repo`` scenario, which was
purpose-built to exercise every tricky metric rule from the brief: plain
edits, a pure rename, a rename+edit, a deletion, a binary file, a mailmap
merge, and a merge commit that must be excluded.
"""
from __future__ import annotations

from app.services import analyzer, gitlog

ALICE = "Alice Dev <alice@example.com>"


def _analyze(fixture_repo):
    commits = list(gitlog.iter_commits(fixture_repo.path))
    return commits, analyzer.analyze_commits(commits)


def test_merge_commit_is_excluded_from_history(fixture_repo):
    commits, result = _analyze(fixture_repo)
    assert result.commit_count == 9
    shas = {c.sha for c in commits}
    assert fixture_repo.rev("merge feature") not in shas
    assert fixture_repo.rev("initial import") in shas


def test_pure_rename_does_not_change_metrics(fixture_repo):
    _, result = _analyze(fixture_repo)
    old = result.objects["README.md"]
    new = result.objects["docs/README.md"]
    # The rename commit itself contributed no added/removed lines anywhere.
    assert new.added == 0 and new.removed == 0
    assert new.modifications == 0
    # The historical content stays attributed to the path that held it then.
    assert old.added == 1 and old.removed == 0


def test_rename_with_edit_attributed_to_new_path_only(fixture_repo):
    _, result = _analyze(fixture_repo)
    old = result.objects["src/util.py"]
    new = result.objects["src/utils.py"]
    # Original 3 lines stay on the old path (added when it was first created).
    assert old.added == 3 and old.removed == 0
    # The rename+edit commit's delta lands only on the new path, not on both.
    assert new.added > 0 or new.removed > 0
    # Touched twice: the rename+edit (Bob) and a later plain edit (Alice).
    assert new.modifications == 2
    assert new.author_modifications.get("Bob Builder <bob@example.com>") == 1


def test_deletion_recorded_as_removed_lines_on_its_path(fixture_repo):
    _, result = _analyze(fixture_repo)
    run_sh = result.objects["bin/run.sh"]
    assert run_sh.added == 2  # added when created (2 lines)
    assert run_sh.removed == 2  # fully removed on deletion
    assert run_sh.growth == 0
    assert run_sh.modifications == 2  # created, then deleted


def test_binary_files_are_not_measured(fixture_repo):
    _, result = _analyze(fixture_repo)
    assert "assets/logo.bin" not in result.objects
    # Its parent directory never receives any lines either -- it has no
    # non-binary descendant anywhere in the fixture.
    assert "assets" not in result.objects


def test_mailmap_merges_alternate_author_email(fixture_repo):
    _, result = _analyze(fixture_repo)
    assert ALICE in result.authors
    assert "alice <alice@other.test>" not in result.authors
    utils = result.objects["src/utils.py"]
    # The commit under the alternate email is counted under the merged name.
    assert utils.author_modifications.get(ALICE, 0) >= 1


def test_directory_metrics_equal_sum_of_immediate_children(fixture_repo):
    """Directory metrics must equal the sum over immediate children -- the
    recursive aggregation rule from the brief, checked structurally against
    whatever the analyzer actually produced (not hand-computed numbers).
    """
    _, result = _analyze(fixture_repo)
    for obj in result.directories():
        prefix = f"{obj.path}/" if obj.path else ""
        children = [
            other
            for other in result.objects.values()
            if other.path != obj.path
            and other.path.startswith(prefix)
            and "/" not in other.path[len(prefix):]
        ]
        assert obj.added == sum(c.added for c in children), obj.path
        assert obj.removed == sum(c.removed for c in children), obj.path


def test_repository_is_directory_metrics_on_root(fixture_repo):
    _, result = _analyze(fixture_repo)
    top_level = [
        o for o in result.objects.values() if o.path and "/" not in o.path
    ]
    assert result.repository.added == sum(o.added for o in top_level)
    assert result.repository.removed == sum(o.removed for o in top_level)


def test_modification_frequency_and_churn_rate(fixture_repo):
    _, result = _analyze(fixture_repo)
    n = result.commit_count
    run_sh = result.objects["bin/run.sh"]
    assert run_sh.modification_frequency(n) == run_sh.modifications / n
    assert run_sh.churn_rate(n) == run_sh.churn / n
    empty = analyzer.ObjectStats(path="x", is_dir=False)
    assert empty.modification_frequency(0) == 0.0
    assert empty.churn_rate(0) == 0.0


def test_author_ownership_fraction(fixture_repo):
    _, result = _analyze(fixture_repo)
    main_py = result.objects["src/main.py"]
    total_ownership = sum(
        main_py.ownership(a) for a in main_py.author_added
    )
    assert abs(total_ownership - 1.0) < 1e-9
    empty = analyzer.ObjectStats(path="x", is_dir=False)
    assert empty.ownership("nobody") == 0.0

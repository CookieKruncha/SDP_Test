"""Validates the deterministic fixture-repository builder itself.

The fixture repo is the backbone of all metric golden-value tests in later
stages, so its structure (commit counts, renames, binary files) is asserted
here via plain git commands.
"""


def test_fixture_repo_has_expected_commit_counts(fixture_repo):
    assert len(fixture_repo.commits) == 10
    assert int(fixture_repo.run("rev-list", "--count", "HEAD")) == 10
    assert int(fixture_repo.run("rev-list", "--count", "--no-merges", "HEAD")) == 9


def test_fixture_repo_rename_is_detected(fixture_repo):
    renames = fixture_repo.run(
        "log", "--diff-filter=R", "--name-status", "--format=", "-M50%"
    )
    assert "src/utils.py" in renames
    assert "docs/README.md" in renames


def test_fixture_repo_binary_file_is_binary_to_git(fixture_repo):
    numstat = fixture_repo.run(
        "show", "--numstat", "--format=", fixture_repo.rev("add binary asset")
    )
    assert "-\t-\tassets/logo.bin" in numstat

"""Shared pytest fixtures, including a deterministic fixture-repository builder."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from app import create_app

# Deterministic base timestamp (2020-09-13T12:26:40Z) and identities used to
# build fixture repositories with stable committer dates and authors.
T0 = 1_600_000_000
ALICE = ("Alice Dev", "alice@example.com")
ALICE_ALT = ("alice", "alice@other.test")
BOB = ("Bob Builder", "bob@example.com")
CAROL = ("Carol Coder", "carol@example.com")


class GitRepo:
    """Helper around the git CLI for building deterministic fixture repositories.

    Commit timestamps and authors are controlled via environment variables so
    tests can rely on exact committer dates and identities.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.commits: dict[str, str] = {}
        self.run("init", "-b", "main")
        self.run("config", "user.name", "Fixture Bot")
        self.run("config", "user.email", "fixture@example.com")

    def run(
        self,
        *args: str,
        when: int | None = None,
        identity: tuple[str, str] | None = None,
    ) -> str:
        env = os.environ.copy()
        if when is not None:
            stamp = f"{when} +0000"
            env["GIT_AUTHOR_DATE"] = stamp
            env["GIT_COMMITTER_DATE"] = stamp
        if identity is not None:
            name, email = identity
            env["GIT_AUTHOR_NAME"] = name
            env["GIT_AUTHOR_EMAIL"] = email

        result = subprocess.run(
            ["git", *args], cwd=self.path, env=env, capture_output=True, text=True
        )
        if result.returncode != 0:
            raise AssertionError(f"git {' '.join(args)} failed:\n{result.stderr}")
        return result.stdout

    def write(self, relpath: str, content: str | bytes) -> None:
        target = self.path / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content)

    def remove(self, relpath: str) -> None:
        (self.path / relpath).unlink()

    def move(self, src: str, dst: str) -> None:
        (self.path / dst).parent.mkdir(parents=True, exist_ok=True)
        self.run("mv", src, dst)

    def commit(self, label: str, when: int, identity: tuple[str, str] = ALICE) -> str:
        self.run("add", "-A")
        self.run("commit", "-m", label, when=when, identity=identity)
        sha = self.run("rev-parse", "HEAD").strip()
        self.commits[label] = sha
        return sha

    def rev(self, label: str) -> str:
        return self.commits[label]


def build_fixture_repo(root: Path) -> GitRepo:
    """Build the standard metric-test scenario.

    Scenario coverage (used by golden-value tests in later stages):
      - plain adds and edits
      - pure rename (README.md -> docs/README.md) — must not change metrics
      - rename + edit (src/util.py -> src/utils.py) — attributed to new path
      - deletion (bin/run.sh) — recorded as removed lines on its path
      - binary file (assets/logo.bin) — not measured
      - one author with two emails (.mailmap maps the alternate email)
      - a merge commit (--no-ff) that must be excluded from analysis
    """
    repo = GitRepo(root)

    repo.write("README.md", "# Fixture\n")
    repo.write("src/main.py", "print('one')\nprint('two')\nprint('three')\nprint('four')\n")
    repo.write("bin/run.sh", "#!/bin/sh\necho run\n")
    repo.commit("initial import", T0, identity=ALICE)

    repo.write(
        "src/main.py",
        "print('one')\nprint('TWO CHANGED')\nprint('three')\nprint('four')\nprint('five')\n",
    )
    repo.write("src/util.py", "def util():\n    value = 1\n    return value\n")
    repo.commit("edit main, add util", T0 + 100, identity=ALICE)

    repo.move("README.md", "docs/README.md")
    repo.commit("pure rename readme", T0 + 200, identity=ALICE)

    repo.write("src/util.py", "def util():\n    value = 2\n    return value\n")
    repo.move("src/util.py", "src/utils.py")
    repo.commit("rename util with edit", T0 + 300, identity=BOB)

    repo.remove("bin/run.sh")
    repo.commit("delete run script", T0 + 400, identity=BOB)

    repo.write("assets/logo.bin", bytes(range(256)))
    repo.commit("add binary asset", T0 + 500, identity=BOB)

    repo.write(".mailmap", "Alice Dev <alice@example.com> <alice@other.test>\n")
    repo.write("src/utils.py", "def util():\n    value = 3\n    return value\n")
    repo.commit("alternate alice email", T0 + 600, identity=ALICE_ALT)

    # Feature branch merged with --no-ff: the merge commit must be excluded,
    # while both parent commits remain in scope.
    repo.run("checkout", "-b", "feature", when=T0 + 700)
    repo.write("docs/guide.md", "# Guide\n")
    repo.commit("add guide on branch", T0 + 700, identity=CAROL)
    repo.run("checkout", "main", when=T0 + 800)
    repo.write(
        "src/main.py",
        "print('one')\nprint('TWO CHANGED')\nprint('three')\n"
        "print('four')\nprint('five')\nprint('six')\n",
    )
    repo.commit("extend main on main", T0 + 800, identity=CAROL)
    repo.run("merge", "--no-ff", "feature", "-m", "merge feature", when=T0 + 900, identity=CAROL)
    repo.commits["merge feature"] = repo.run("rev-parse", "HEAD").strip()
    return repo


@pytest.fixture(scope="session")
def fixture_repo(tmp_path_factory) -> GitRepo:
    """A read-only fixture repository shared across tests."""
    root = tmp_path_factory.mktemp("fixture-repo-src") / "repo"
    return build_fixture_repo(root)


@pytest.fixture()
def app(tmp_path):
    """Flask app with all runtime paths relocated to a temp directory."""
    return create_app(
        INSTANCE_DIR=tmp_path / "instance",
        REPOS_DIR=tmp_path / "instance" / "repos",
        UPLOADS_DIR=tmp_path / "instance" / "uploads",
        DATABASE_PATH=tmp_path / "instance" / "rat.db",
        TESTING=True,
    )


@pytest.fixture()
def client(app):
    return app.test_client()

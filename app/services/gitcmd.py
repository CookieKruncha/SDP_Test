"""Exact wrappers around the git CLI.

All git access in RAT goes through this module so behaviour stays identical
everywhere:

- ``safe.directory`` is bypassed for repos we manage (uploads may be owned by
  a different user than the server process);
- credential prompts are disabled so jobs fail fast with a friendly error
  instead of hanging on a terminal prompt;
- stderr is always captured for error reporting.
"""
from __future__ import annotations

import os
import subprocess

GIT_PREFIX = ("git", "-c", "safe.directory=*")


class GitError(RuntimeError):
    """A git invocation exited non-zero."""

    def __init__(self, argv, returncode: int, stderr: str):
        self.argv = tuple(argv)
        self.returncode = returncode
        self.stderr = stderr or ""
        super().__init__(
            f"git {' '.join(argv)} failed with exit code {returncode}: {self.stderr.strip()}"
        )


def env() -> dict:
    """Environment for git subprocesses (no prompts, no hangs)."""
    result = os.environ.copy()
    result.setdefault("GIT_TERMINAL_PROMPT", "0")
    result.setdefault(
        "GIT_SSH_COMMAND",
        "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new",
    )
    return result


def run(args, cwd=None, timeout=None) -> subprocess.CompletedProcess:
    """Run git and capture stdout/stderr as text (never raises on failure)."""
    return subprocess.run(
        [*GIT_PREFIX, *args],
        cwd=cwd,
        env=env(),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def output(args, cwd=None) -> str:
    """Run git and return stripped stdout; raise GitError on failure."""
    result = run(args, cwd=cwd)
    if result.returncode != 0:
        raise GitError(args, result.returncode, result.stderr)
    return result.stdout.strip()


def stream(args, cwd=None) -> subprocess.Popen:
    """Popen with stdout+stderr merged, line-buffered (for progress parsing)."""
    return subprocess.Popen(
        [*GIT_PREFIX, *args],
        cwd=cwd,
        env=env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

"""Repository ingestion: zip uploads and URL clones.

Invariants (relied on by every later stage):

- Zip extraction is **zip-slip-safe**: every member must resolve inside the
  repository directory, otherwise the whole archive is rejected.
- A repo is only marked ``ready`` after ``git rev-parse`` proved the
  checkout usable and ``HEAD`` exists, so the analyzer can always trust
  ``repos.path``.
- URL clones are full mirrors (``git clone --mirror``): no worktree, all
  refs — the analyzer can run at any reference commit.
- git never prompts for credentials (see :mod:`app.services.gitcmd`), so
  auth/network failures surface as friendly job errors instead of hanging.
"""

from __future__ import annotations

import re
import shutil
import zipfile
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from . import gitcmd, registry

_URL_SCHEMES = {"http", "https", "ssh", "git", "file"}
_SCHEME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*)://")
_SCP_RE = re.compile(r"^[^/@\s]+@[^/:\s]+:")  # git@github.com:owner/repo.git
_PCT_RE = re.compile(r"(\d{1,3})%")
_DRIVE_RE = re.compile(r"^[A-Za-z]:")


class IngestError(Exception):
    """Human-readable ingestion failure (the message is shown in the UI)."""

    def __init__(self, message: str, code: str = "invalid_input"):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class IngestContext:
    """Plain config snapshot that is safe to hand to worker threads."""

    db_path: Path
    repos_dir: Path
    uploads_dir: Path

    @classmethod
    def from_config(cls, config) -> "IngestContext":
        return cls(
            db_path=Path(config["DATABASE_PATH"]),
            repos_dir=Path(config["REPOS_DIR"]),
            uploads_dir=Path(config["UPLOADS_DIR"]),
        )


# --- Source validation (synchronous, before any repo/job row exists) --------


def validate_url(raw: str) -> str:
    """Validate a clone source; returns the cleaned URL or raises IngestError."""
    url = (raw or "").strip()
    if not url:
        raise IngestError("Enter a repository URL.", "invalid_url")
    if len(url) > 2048:
        raise IngestError("That URL is too long (2048 characters max).", "invalid_url")
    match = _SCHEME_RE.match(url)
    if match:
        scheme = match.group(1).lower()
        if scheme not in _URL_SCHEMES:
            raise IngestError(
                f"Unsupported URL scheme '{scheme}://' — use https://, ssh:// or git://.",
                "invalid_url",
            )
        return url
    if _SCP_RE.match(url) or url.startswith("/") or url.startswith("./"):
        return url  # scp-style ssh address or a local path
    raise IngestError(
        "That does not look like a repository URL — use e.g. "
        "https://github.com/owner/repo.git.",
        "invalid_url",
    )


def repo_name_from_url(url: str) -> str:
    tail = re.split(r"[/:]", url.rstrip("/"))[-1]
    if tail.endswith(".git"):
        tail = tail[:-4]
    return tail or "repository"


def repo_name_from_filename(filename: str) -> str:
    name = Path(filename or "").name
    if name.lower().endswith(".zip"):
        name = name[:-4]
    return name.strip() or "upload"


def find_repo_root(names) -> str | None:
    """Shallowest directory inside the archive that contains a ``.git`` entry.

    Works on the zip namelist so bad archives can be rejected before anything
    is written to disk. ``""`` means the archive root itself.
    """
    candidates: set[str] = set()
    for raw in names:
        parts = [p for p in raw.replace("\\", "/").split("/") if p not in ("", ".")]
        if ".git" in parts:
            candidates.add("/".join(parts[: parts.index(".git")]))
    if not candidates:
        return None
    return min(candidates, key=lambda p: (len(p.split("/")) if p else 0, p))


def _unsafe_member_reason(name: str) -> str | None:
    normalized = name.replace("\\", "/")
    if normalized.startswith("/"):
        return "absolute path"
    if _DRIVE_RE.match(normalized):
        return "drive-letter path"
    if ".." in normalized.split("/"):
        return "parent-directory escape"
    return None


def stage_upload(file_storage, uploads_dir: Path, staging_id: str) -> Path:
    """Persist a multipart upload and run the cheap synchronous checks.

    Rejects non-zips, empty/password-protected archives, unsafe paths and
    archives without ``.git`` *before* a repo row or background job exists.
    Returns the staged zip path (deleted by the worker after extraction).
    """
    uploads_dir = Path(uploads_dir)
    uploads_dir.mkdir(parents=True, exist_ok=True)
    staging = uploads_dir / f"{staging_id}.zip"
    try:
        file_storage.save(staging)
    except OSError as exc:
        raise IngestError(
            f"The upload could not be stored on disk: {exc}", "disk_error"
        ) from exc

    try:
        _validate_staged_zip(staging)
    except IngestError:
        staging.unlink(missing_ok=True)
        raise
    return staging


def _validate_staged_zip(staging: Path) -> None:
    if not zipfile.is_zipfile(staging):
        raise IngestError("That file is not a valid zip archive.", "invalid_zip")
    try:
        with zipfile.ZipFile(staging) as archive:
            members = archive.infolist()
            if not members:
                raise IngestError("The zip archive is empty.", "invalid_zip")
            if any(member.flag_bits & 0x1 for member in members):
                raise IngestError(
                    "Password-protected archives are not supported.", "invalid_zip"
                )
            for member in members:
                reason = _unsafe_member_reason(member.filename)
                if reason:
                    raise IngestError(
                        f"The archive contains an unsafe path ({reason}): "
                        f"{member.filename!r}.",
                        "unsafe_archive",
                    )
            if find_repo_root(member.filename for member in members) is None:
                raise IngestError(
                    "The archive does not contain a git repository — upload a zip "
                    "that includes the hidden .git folder.",
                    "missing_git",
                )
    except zipfile.BadZipFile as exc:
        raise IngestError(
            "The zip archive could not be read — it may be corrupted or truncated.",
            "invalid_zip",
        ) from exc


# --- Background tasks -------------------------------------------------------


def run_upload_task(
    ctx: IngestContext, repo_id: str, staging_zip: Path, reporter
) -> None:
    """Extract + validate an uploaded archive; marks the repo ready on success."""
    dest = Path(ctx.repos_dir) / repo_id
    try:
        reporter.set(phase="extracting", progress=0.0)
        extract_zip(Path(staging_zip), dest, reporter)
        reporter.set(phase="validating")
        root = locate_repo_root(dest)
        if root is None:
            raise IngestError(
                "The archive does not contain a git repository — a .git folder "
                "is required.",
                "missing_git",
            )
        info = inspect_git_repo(root)
    except IngestError:
        _cleanup_dir(dest, ctx.repos_dir)
        raise
    except OSError as exc:
        _cleanup_dir(dest, ctx.repos_dir)
        raise IngestError(
            f"Ingestion failed with a filesystem error: {exc}", "disk_error"
        ) from exc
    finally:
        try:
            Path(staging_zip).unlink(missing_ok=True)
        except OSError:
            pass
    registry.update_repo(
        ctx.db_path, repo_id, status="ready", path=str(root), error=None, **info
    )


def run_clone_task(ctx: IngestContext, repo_id: str, url: str, reporter) -> None:
    """Mirror-clone + validate a remote repository; marks the repo ready on success."""
    dest = Path(ctx.repos_dir) / repo_id
    try:
        clone_mirror(url, dest, reporter)
        reporter.set(phase="validating")
        info = inspect_git_repo(dest)
    except IngestError:
        _cleanup_dir(dest, ctx.repos_dir)
        raise
    except OSError as exc:
        _cleanup_dir(dest, ctx.repos_dir)
        raise IngestError(
            f"Ingestion failed with a filesystem error: {exc}", "disk_error"
        ) from exc
    registry.update_repo(
        ctx.db_path, repo_id, status="ready", path=str(dest), error=None, **info
    )


# --- Implementation helpers --------------------------------------------------


def extract_zip(zip_path: Path, dest_dir: Path, reporter) -> None:
    """Extract a pre-validated archive, zip-slip-safe, reporting progress."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_root = dest_dir.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        members = archive.infolist()
        total = len(members)
        for index, member in enumerate(members, start=1):
            normalized = member.filename.replace("\\", "/")
            if not normalized or normalized.endswith("/") or member.is_dir():
                reporter.set(phase="extracting", progress=index / total)
                continue
            target = (dest_root / normalized).resolve()
            if target == dest_root:
                continue
            if not target.is_relative_to(dest_root):
                raise IngestError(
                    f"Refusing to extract unsafe path {member.filename!r}.",
                    "unsafe_archive",
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, open(target, "wb") as out:
                shutil.copyfileobj(source, out)
            reporter.set(phase="extracting", progress=index / total)
    reporter.set(phase="extracting", progress=1.0)


def locate_repo_root(base: Path) -> Path | None:
    """Shallowest directory under ``base`` that contains a ``.git`` entry."""
    matches = sorted(
        base.rglob(".git"), key=lambda p: (len(p.relative_to(base).parts), str(p))
    )
    return matches[0].parent if matches else None


def inspect_git_repo(path: Path) -> dict:
    """Validate a checkout and return its HEAD + commit counts."""
    probe = gitcmd.run(["rev-parse", "--git-dir"], cwd=path)
    if probe.returncode != 0:
        raise IngestError(
            "The archive does not contain a usable git repository.", "invalid_repo"
        )
    head = gitcmd.run(["rev-parse", "--verify", "HEAD^{commit}"], cwd=path)
    if head.returncode != 0:
        # Note: plain ``rev-parse HEAD`` is not enough here — on a repo with
        # an unborn HEAD (no commits) it prints the literal string "HEAD"
        # and exits 0; ``--verify HEAD^{commit}`` fails properly.
        raise IngestError(
            "The repository has no commits, so there is nothing to analyse.",
            "empty_repo",
        )
    return {
        "head_sha": head.stdout.strip(),
        "commit_count": int(gitcmd.output(["rev-list", "--count", "HEAD"], cwd=path)),
        "non_merge_count": int(
            gitcmd.output(["rev-list", "--count", "--no-merges", "HEAD"], cwd=path)
        ),
    }


def clone_mirror(url: str, dest: Path, reporter) -> None:
    """``git clone --mirror`` with progress parsed from the child's stderr."""
    reporter.set(phase="cloning", progress=0.0)
    tail: deque[str] = deque(maxlen=30)
    process = gitcmd.stream(["clone", "--mirror", "--progress", url, str(dest)])
    try:
        for raw_line in process.stdout:
            line = raw_line.strip()
            if line:
                tail.append(line)
            match = _PCT_RE.search(line)
            if match:
                reporter.set(
                    phase="cloning", progress=min(int(match.group(1)) / 100.0, 0.95)
                )
    finally:
        returncode = process.wait()
    if returncode != 0:
        raise IngestError(_friendly_clone_error(url, tail), "clone_failed")


def _friendly_clone_error(url: str, lines) -> str:
    detail = ""
    for line in lines:
        if "fatal:" in line:
            detail = line.split("fatal:", 1)[1].strip()
    if not detail and lines:
        detail = lines[-1].strip()
    lowered = detail.lower()
    if "could not resolve host" in lowered or "name or service not known" in lowered:
        return f"Clone failed: the host could not be resolved — check the URL ({url})."
    if (
        "authentication failed" in lowered
        or "could not read username" in lowered
        or "terminal prompts disabled" in lowered
        or "permission denied" in lowered
        or "publickey" in lowered
    ):
        return (
            "Clone failed: authentication failed or credentials are required "
            "for this repository."
        )
    if (
        "not found" in lowered
        or "does not exist" in lowered
        or "does not appear to be a git repository" in lowered
    ):
        return "Clone failed: the repository was not found — check the URL."
    if detail:
        return f"Clone failed: {detail}"
    return f"Clone failed: git exited with a non-zero status (URL: {url})."


def _cleanup_dir(dest: Path, repos_dir) -> None:
    """Remove a partial clone/extraction, guarded to stay inside ``repos_dir``."""
    try:
        root = Path(repos_dir).resolve()
        resolved = dest.resolve()
        if resolved != root and resolved.is_relative_to(root) and resolved.exists():
            shutil.rmtree(resolved, ignore_errors=True)
    except OSError:  # pragma: no cover — best-effort cleanup
        pass

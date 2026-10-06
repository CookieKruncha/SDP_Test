"""Static configuration for the RAT Flask application."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    """Default configuration; overridable in tests via create_app(**overrides)."""

    # --- Storage layout ------------------------------------------------
    INSTANCE_DIR = BASE_DIR / "instance"            # runtime data (git-ignored)
    REPOS_DIR = INSTANCE_DIR / "repos"              # mirror clones / extracted uploads
    UPLOADS_DIR = INSTANCE_DIR / "uploads"          # staged zip uploads
    DATABASE_PATH = INSTANCE_DIR / "rat.db"         # SQLite metric cache
    FRONTEND_DIST = BASE_DIR / "frontend" / "dist"  # built React SPA

    # --- Behaviour ------------------------------------------------------
    MAX_CONTENT_LENGTH = 512 * 1024 * 1024  # 512 MB cap for zip uploads
    SCHEMA_VERSION = 1                      # bump when the cache schema changes

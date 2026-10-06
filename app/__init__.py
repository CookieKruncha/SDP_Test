"""RAT — Repository Analysis Tool: Flask application factory."""
from pathlib import Path

from flask import Flask

from . import db
from .config import Config
from .errors import register_error_handlers
from .routes import register_routes
from .routes.spa import register_spa
from .services import jobs


def create_app(config_object=Config, **overrides):
    """Create and configure the Flask application.

    ``overrides`` are applied on top of ``config_object`` so tests can
    relocate the instance directory to a temporary path.
    """
    app = Flask(__name__)
    app.config.from_object(config_object)
    if overrides:
        app.config.from_mapping(overrides)
    app.json.sort_keys = False  # keep API payload key order stable

    _ensure_instance_dirs(app)
    db.init_db(app.config["DATABASE_PATH"], app.config["SCHEMA_VERSION"])
    _recover_interrupted_jobs(app)

    register_routes(app)
    register_error_handlers(app)
    register_spa(app)
    return app


def _ensure_instance_dirs(app):
    """Create the runtime directories on first boot (idempotent)."""
    for key in ("INSTANCE_DIR", "REPOS_DIR", "UPLOADS_DIR"):
        Path(app.config[key]).mkdir(parents=True, exist_ok=True)


def _recover_interrupted_jobs(app):
    """Fail ingest rows that a previous server process left mid-flight."""
    count = jobs.recover_interrupted_jobs(app.config["DATABASE_PATH"])
    if count:
        app.logger.warning("Recovered %d interrupted ingest job(s) as failed", count)

"""Health and diagnostic endpoints."""
from flask import Blueprint, current_app

bp = Blueprint("health", __name__, url_prefix="/api")


@bp.get("/healthz")
def healthz():
    """Liveness probe used by the frontend to display API connectivity."""
    return {
        "status": "ok",
        "service": "rat",
        "schema_version": current_app.config["SCHEMA_VERSION"],
    }

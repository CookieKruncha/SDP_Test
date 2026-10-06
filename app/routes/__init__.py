"""API blueprint registration."""
from .health import bp as health_bp


def register_routes(app) -> None:
    app.register_blueprint(health_bp)

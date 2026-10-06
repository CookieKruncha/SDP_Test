"""API blueprint registration."""
from .health import bp as health_bp
from .jobs import bp as jobs_bp
from .repos import bp as repos_bp


def register_routes(app) -> None:
    app.register_blueprint(health_bp)
    app.register_blueprint(repos_bp)
    app.register_blueprint(jobs_bp)

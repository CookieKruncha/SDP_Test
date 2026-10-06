"""Consistent JSON error payloads for API routes.

Every /api response on failure has the shape:
    {"error": {"code": "...", "message": "..."}}
Non-API paths keep Flask/Werkzeug default HTML error pages.
"""
from flask import jsonify, request
from werkzeug.exceptions import HTTPException


class ApiError(Exception):
    """Application error that renders as a JSON payload."""

    def __init__(self, message: str, status: int = 400, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code or f"http_{status}"


def register_error_handlers(app) -> None:
    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return _payload(err.message, err.code, err.status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(err: HTTPException):
        if _is_api_request():
            return _payload(err.description, f"http_{err.code}", err.code)
        return err

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):
        if isinstance(err, HTTPException):
            return handle_http_exception(err)
        app.logger.exception("Unhandled error on %s %s", request.method, request.path)
        if _is_api_request():
            return _payload("Internal server error", "internal_error", 500)
        return "Internal Server Error", 500


def _is_api_request() -> bool:
    return request.path == "/api" or request.path.startswith("/api/")


def _payload(message, code, status):
    return jsonify({"error": {"code": code, "message": message}}), status

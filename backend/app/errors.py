from contextlib import contextmanager

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from app.scrapers import ScraperError
from app.services.watches import AlreadyWatchingError, NotFoundError


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def error_response(status: int, code: str, message: str):
    return jsonify({"error": {"code": code, "message": message}}), status


@contextmanager
def validation():
    """Turn model validation errors (ValueError) into 400 responses."""
    try:
        yield
    except ValueError as exc:
        raise ApiError(400, "invalid_request", str(exc)) from None


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def handle_api_error(error: ApiError):
        return error_response(error.status, error.code, error.message)

    @app.errorhandler(NotFoundError)
    def handle_not_found(error: NotFoundError):
        return error_response(404, "not_found", str(error))

    @app.errorhandler(AlreadyWatchingError)
    def handle_already_watching(error: AlreadyWatchingError):
        return error_response(409, "already_watching", str(error))

    @app.errorhandler(ScraperError)
    def handle_scraper_error(error: ScraperError):
        app.logger.warning("Scrape failed during request: %s", error)
        return error_response(
            502, "scrape_failed", "Could not fetch the product from the store"
        )

    @app.errorhandler(HTTPException)
    def handle_http_exception(error: HTTPException):
        code = (error.name or "error").lower().replace(" ", "_")
        return error_response(error.code or 500, code, error.description or error.name)

    @app.errorhandler(Exception)
    def handle_unexpected(error: Exception):
        app.logger.exception("Unhandled error")
        return error_response(500, "internal_error", "Internal server error")

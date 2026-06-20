from flask import Flask, request

ALLOWED_METHODS = "GET, POST, PATCH, DELETE, OPTIONS"
ALLOWED_HEADERS = "Authorization, Content-Type"


def init_cors(app: Flask) -> None:
    """Allow cross-origin API calls from the configured frontend origin only."""

    @app.after_request
    def add_cors_headers(response):
        origin = request.headers.get("Origin")
        allowed = app.config.get("FRONTEND_ORIGIN")

        if origin and allowed and origin == allowed and request.path.startswith("/api/"):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Methods"] = ALLOWED_METHODS
            response.headers["Access-Control-Allow-Headers"] = ALLOWED_HEADERS
            response.headers["Access-Control-Max-Age"] = "600"
            response.headers.add("Vary", "Origin")

        return response

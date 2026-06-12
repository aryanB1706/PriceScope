from flask import Flask

from app.routes.health import health_bp


def register_routes(app: Flask) -> None:
    app.register_blueprint(health_bp)

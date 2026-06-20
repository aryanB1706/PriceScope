from flask import Flask

from app.routes.alerts import alerts_bp
from app.routes.health import health_bp
from app.routes.products import products_bp
from app.routes.watches import watches_bp


def register_routes(app: Flask) -> None:
    app.register_blueprint(health_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(watches_bp)
    app.register_blueprint(alerts_bp)

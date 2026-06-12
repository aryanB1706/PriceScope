from flask import Flask

from app.config import Config
from app.db import init_db
from app.routes import register_routes


def create_app(config_overrides: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

    if config_overrides:
        app.config.update(config_overrides)

    init_db(app)
    register_routes(app)

    return app

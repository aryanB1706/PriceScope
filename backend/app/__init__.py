import click
from flask import Flask

from app.config import Config
from app.db import get_db, init_app as init_mongo
from app.models import init_db
from app.routes import register_routes


def create_app(config_overrides: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

    if config_overrides:
        app.config.update(config_overrides)

    init_mongo(app)
    register_routes(app)

    @app.cli.command("init-db")
    def init_db_command():
        init_db(get_db())
        click.echo("Database indexes initialized.")

    return app

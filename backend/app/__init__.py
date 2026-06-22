import click
from flask import Flask

from app.config import Config
from app.cors import init_cors
from app.db import get_db, init_app as init_mongo
from app.errors import register_error_handlers
from app.jobs.scheduler import init_scheduler, run_scrape_job
from app.models import init_db
from app.routes import register_routes
from app.services.alerts import init_alerts


def create_app(config_overrides: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

    if config_overrides:
        app.config.update(config_overrides)

    init_mongo(app)
    init_cors(app)
    register_error_handlers(app)
    register_routes(app)
    init_alerts(app)
    init_scheduler(app)

    @app.cli.command("init-db")
    def init_db_command():
        init_db(get_db())
        click.echo("Database indexes initialized.")

    @app.cli.command("scrape-now")
    def scrape_now_command():
        summary = run_scrape_job(get_db(), trigger="manual")
        click.echo(
            f"Checked {summary.products_checked} products: "
            f"{summary.succeeded} succeeded, {summary.failed} failed, "
            f"{summary.price_changes} price changes "
            f"({summary.duration_seconds:.1f}s)."
        )

    return app

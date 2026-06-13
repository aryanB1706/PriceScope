from flask import current_app
from pymongo import MongoClient
from pymongo.database import Database


def init_app(app) -> None:
    client = MongoClient(
        app.config["MONGO_URI"],
        serverSelectionTimeoutMS=app.config["MONGO_SERVER_SELECTION_TIMEOUT_MS"],
        tz_aware=True,
    )
    app.extensions["mongo_client"] = client
    app.extensions["mongo_db"] = client[app.config["MONGO_DB_NAME"]]


def get_db() -> Database:
    db = current_app.extensions.get("mongo_db")
    if db is None:
        raise RuntimeError("MongoDB has not been initialized")
    return db


def ping_db() -> bool:
    client = current_app.extensions.get("mongo_client")
    if client is None:
        raise RuntimeError("MongoDB has not been initialized")
    client.admin.command("ping")
    return True

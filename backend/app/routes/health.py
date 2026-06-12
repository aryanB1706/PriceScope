from flask import Blueprint, current_app, jsonify
from pymongo.errors import PyMongoError

from app.db import ping_db

health_bp = Blueprint("health", __name__, url_prefix="/api")


@health_bp.get("/health")
def health():
    try:
        ping_db()
    except PyMongoError:
        current_app.logger.exception("MongoDB health check failed")
        return jsonify({"status": "error", "database": "unavailable"}), 503

    return jsonify({"status": "ok", "database": "ok"})

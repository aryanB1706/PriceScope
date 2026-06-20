from flask import Blueprint, g, jsonify

from app.db import get_db
from app.routes.parsing import int_query_param
from app.routes.serializers import alert_json
from app.services import watches
from app.services.auth import require_auth

alerts_bp = Blueprint("alerts", __name__, url_prefix="/api")


@alerts_bp.get("/alerts")
@require_auth
def list_alerts():
    limit = int_query_param("limit", default=50, minimum=1, maximum=200)
    items = watches.list_alerts(get_db(), g.user_id, limit)
    return jsonify({"alerts": [alert_json(i["alert"], i["product"]) for i in items]})

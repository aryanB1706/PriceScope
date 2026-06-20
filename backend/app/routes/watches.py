from flask import Blueprint, g, jsonify

from app.db import get_db
from app.errors import ApiError
from app.routes.parsing import (
    json_body,
    parse_alert_flag,
    parse_target_price,
    reject_unknown_fields,
)
from app.routes.serializers import watch_json
from app.services import watches
from app.services.auth import require_auth

watches_bp = Blueprint("watches", __name__, url_prefix="/api")


@watches_bp.patch("/watches/<watch_id>")
@require_auth
def update_watch(watch_id: str):
    body = json_body()
    reject_unknown_fields(body, {"target_price", "alert_on_30d_low"})
    if not body:
        raise ApiError(
            400, "invalid_request", "Provide target_price and/or alert_on_30d_low"
        )

    changes = {}
    if "target_price" in body:
        changes["target_price"] = parse_target_price(body["target_price"])
    if "alert_on_30d_low" in body:
        changes["alert_on_30d_low"] = parse_alert_flag(body["alert_on_30d_low"])

    watch = watches.update_watch(get_db(), g.user_id, watch_id, changes)
    return jsonify({"watch": watch_json(watch)})


@watches_bp.delete("/watches/<watch_id>")
@require_auth
def delete_watch(watch_id: str):
    watches.delete_watch(get_db(), g.user_id, watch_id)
    return "", 204

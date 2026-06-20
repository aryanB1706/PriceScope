from flask import Blueprint, g, jsonify

from app.db import get_db
from app.routes.parsing import (
    int_query_param,
    json_body,
    parse_alert_flag,
    parse_store_url,
    parse_target_price,
    reject_unknown_fields,
)
from app.routes.serializers import (
    money,
    price_point_json,
    product_json,
    watch_json,
    watched_product_json,
)
from app.services import watches
from app.services.auth import require_auth

products_bp = Blueprint("products", __name__, url_prefix="/api")


@products_bp.post("/products")
@require_auth
def add_product():
    body = json_body()
    reject_unknown_fields(body, {"url", "target_price", "alert_on_30d_low"})

    url = parse_store_url(body.get("url"))
    target_price = parse_target_price(body.get("target_price"))
    alert_on_30d_low = parse_alert_flag(body.get("alert_on_30d_low", False))

    product, watch = watches.create_watch(
        get_db(), g.user_id, url, target_price, alert_on_30d_low
    )
    return jsonify({"product": product_json(product), "watch": watch_json(watch)}), 201


@products_bp.get("/products")
@require_auth
def list_products():
    items = watches.list_watched_products(get_db(), g.user_id)
    return jsonify({"products": [watched_product_json(item) for item in items]})


@products_bp.get("/products/<product_id>/history")
@require_auth
def product_history(product_id: str):
    days = int_query_param("days", default=30, minimum=1, maximum=365)
    product, summary = watches.get_watched_history(
        get_db(), g.user_id, product_id, days
    )
    return jsonify(
        {
            "product_id": str(product._id),
            "days": days,
            "points": [price_point_json(point) for point in summary.points],
            "min_price": money(summary.min_price),
            "max_price": money(summary.max_price),
            "current_price": money(summary.current_price),
        }
    )

from datetime import datetime
from decimal import Decimal

from app.models import Alert, PriceHistory, Product, Watch


def money(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def product_json(product: Product) -> dict:
    return {
        "id": str(product._id),
        "store": product.store.value,
        "url": product.url,
        "title": product.title,
        "image_url": product.image_url,
        "current_price": money(product.current_price),
        "currency": product.currency,
        "last_checked_at": timestamp(product.last_checked_at),
    }


def watch_json(watch: Watch) -> dict:
    return {
        "id": str(watch._id),
        "product_id": str(watch.product_id),
        "target_price": money(watch.target_price),
        "alert_on_30d_low": watch.alert_on_30d_low,
        "created_at": timestamp(watch.created_at),
        "last_alerted_at": timestamp(watch.last_alerted_at),
    }


def watched_product_json(item: dict) -> dict:
    return {
        **product_json(item["product"]),
        "product_id": str(item["product"]._id),
        "watch": watch_json(item["watch"]),
        "in_stock": item["in_stock"],
        "lowest_price": money(item["lowest_price"]),
        "highest_price": money(item["highest_price"]),
        "is_30d_low": item["is_30d_low"],
    }


def price_point_json(point: PriceHistory) -> dict:
    return {
        "price": money(point.price),
        "in_stock": point.in_stock,
        "scraped_at": timestamp(point.scraped_at),
    }


def alert_json(alert: Alert, product: Product | None) -> dict:
    return {
        "id": str(alert._id),
        "product_id": str(alert.product_id),
        "product_title": product.title if product else None,
        "product_url": product.url if product else None,
        "store": product.store.value if product else None,
        "reason": alert.reason.value,
        "old_price": money(alert.old_price),
        "new_price": money(alert.new_price),
        "detected_at": timestamp(alert.detected_at),
        "sent_at": timestamp(alert.sent_at),
        "email_status": alert.email_status.value,
    }

from dataclasses import replace
from decimal import Decimal

from bson import ObjectId
from pymongo import DESCENDING, ReturnDocument
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.models import Alert, PriceHistory, Product, Watch, validate_object_id
from app.models.validation import to_decimal128
from app.services import tracker


class NotFoundError(LookupError):
    pass


class AlreadyWatchingError(Exception):
    pass


def create_watch(
    db: Database,
    user_id: str,
    url: str,
    target_price: Decimal | None = None,
    alert_on_30d_low: bool = False,
) -> tuple[Product, Watch]:
    """Track a product URL for a user, scraping it once if needed."""
    existing = db.products.find_one({"url": url})
    if existing is not None and db.watches.find_one(
        {"user_id": user_id, "product_id": existing["_id"]}
    ):
        raise AlreadyWatchingError("You are already watching this product")

    product = tracker.add_product(url, db=db)
    watch = Watch(
        user_id=user_id,
        product_id=product._id,
        target_price=target_price,
        alert_on_30d_low=alert_on_30d_low,
    )
    try:
        inserted = db.watches.insert_one(watch.to_document())
    except DuplicateKeyError:
        raise AlreadyWatchingError("You are already watching this product") from None

    return product, replace(watch, _id=inserted.inserted_id)


def list_watched_products(db: Database, user_id: str) -> list[dict]:
    watches = [
        Watch.from_document(doc)
        for doc in db.watches.find({"user_id": user_id}).sort("created_at", DESCENDING)
    ]
    product_ids = [watch.product_id for watch in watches]
    products = {
        doc["_id"]: Product.from_document(doc)
        for doc in db.products.find({"_id": {"$in": product_ids}})
    }

    history: dict[ObjectId, list[PriceHistory]] = {}
    rows = db.price_history.find({"product_id": {"$in": product_ids}}).sort(
        "scraped_at", 1
    )
    for row in rows:
        point = PriceHistory.from_document(row)
        history.setdefault(point.product_id, []).append(point)

    items = []
    for watch in watches:
        product = products.get(watch.product_id)
        if product is None:
            continue

        points = history.get(product._id, [])
        prices = [point.price for point in points]
        items.append(
            {
                "watch": watch,
                "product": product,
                "in_stock": points[-1].in_stock if points else None,
                "lowest_price": min(prices) if prices else None,
                "highest_price": max(prices) if prices else None,
                "is_30d_low": tracker.is_30d_low(product, db=db),
            }
        )
    return items


def get_watched_history(
    db: Database, user_id: str, product_id: str, days: int
) -> tuple[Product, tracker.HistorySummary]:
    try:
        oid = validate_object_id(product_id)
    except ValueError:
        raise NotFoundError("Product not found") from None

    if db.watches.find_one({"user_id": user_id, "product_id": oid}) is None:
        raise NotFoundError("Product not found")

    document = db.products.find_one({"_id": oid})
    if document is None:
        raise NotFoundError("Product not found")

    return Product.from_document(document), tracker.get_history(oid, days, db=db)


def update_watch(db: Database, user_id: str, watch_id: str, changes: dict) -> Watch:
    stored = {
        key: to_decimal128(value) if isinstance(value, Decimal) else value
        for key, value in changes.items()
    }
    document = db.watches.find_one_and_update(
        {"_id": _watch_oid(watch_id), "user_id": user_id},
        {"$set": stored},
        return_document=ReturnDocument.AFTER,
    )
    if document is None:
        raise NotFoundError("Watch not found")
    return Watch.from_document(document)


def delete_watch(db: Database, user_id: str, watch_id: str) -> None:
    result = db.watches.delete_one({"_id": _watch_oid(watch_id), "user_id": user_id})
    if result.deleted_count == 0:
        raise NotFoundError("Watch not found")


def list_alerts(db: Database, user_id: str, limit: int) -> list[dict]:
    alerts = [
        Alert.from_document(doc)
        for doc in db.alerts.find({"user_id": user_id})
        .sort("detected_at", DESCENDING)
        .limit(limit)
    ]
    product_ids = list({alert.product_id for alert in alerts})
    products = {
        doc["_id"]: Product.from_document(doc)
        for doc in db.products.find({"_id": {"$in": product_ids}})
    }
    return [{"alert": alert, "product": products.get(alert.product_id)} for alert in alerts]


def _watch_oid(watch_id: str) -> ObjectId:
    try:
        return validate_object_id(watch_id, "watch_id")
    except ValueError:
        raise NotFoundError("Watch not found") from None

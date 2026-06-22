import logging
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal

from bson import ObjectId
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.db import get_db
from app.models import PriceHistory, Product, validate_object_id, validate_url
from app.models.validation import to_decimal128, utc_now
from app.scrapers import BaseScraper, ScrapedProduct, ScraperError, get_scraper

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = timedelta(hours=24)
LOW_PRICE_WINDOW_DAYS = 30


@dataclass(frozen=True, slots=True)
class HistorySummary:
    points: list[PriceHistory]
    min_price: Decimal | None
    max_price: Decimal | None
    current_price: Decimal | None


def add_product(
    url: str,
    *,
    db: Database | None = None,
    scraper: BaseScraper | None = None,
    now: datetime | None = None,
) -> Product:
    """Start tracking a product URL, or refresh it if it is already tracked.

    Raises ScraperError if the URL has no scraper or the first scrape fails.
    """
    db = db if db is not None else get_db()
    url = validate_url(url)
    now = now or utc_now()

    existing = db.products.find_one({"url": url})
    if existing is not None:
        return record_price(
            Product.from_document(existing), db=db, scraper=scraper, now=now
        )

    scraper = scraper or get_scraper(url)
    scraped = scraper.parse(scraper.fetch(url))

    product = Product(
        store=scraper.store,
        url=url,
        title=scraped["title"],
        image_url=scraped["image_url"],
        current_price=scraped["price"],
        last_checked_at=now,
        created_at=now,
    )

    try:
        result = db.products.insert_one(product.to_document())
    except DuplicateKeyError:
        # Lost a race with a concurrent add of the same URL.
        existing = db.products.find_one({"url": url})
        return record_price(
            Product.from_document(existing), db=db, scraper=scraper, now=now
        )

    product = replace(product, _id=result.inserted_id)
    _insert_history(db, product, scraped, now)
    return product


def record_price(
    product: Product,
    *,
    db: Database | None = None,
    scraper: BaseScraper | None = None,
    now: datetime | None = None,
    alert_dispatcher=None,
) -> Product:
    """Scrape a tracked product and store the result.

    A price_history row is written only when the price or stock status changed,
    or when the last row is more than 24 hours old. If scraping fails, the
    stored price data is left untouched and the failure counter is incremented.
    When the price dropped, matching watches are alerted (emails are sent on a
    background thread, so this never waits on SMTP).
    """
    db = db if db is not None else get_db()
    now = now or utc_now()
    product_id = _require_id(product)

    try:
        scraper = scraper or get_scraper(product.url)
        scraped = scraper.parse(scraper.fetch(product.url))
    except Exception as exc:
        if isinstance(exc, ScraperError):
            logger.warning("Scrape failed for %s: %s", product.url, exc)
        else:
            logger.exception("Unexpected error scraping %s", product.url)
        db.products.update_one(
            {"_id": product_id}, {"$inc": {"consecutive_failures": 1}}
        )
        return replace(product, consecutive_failures=product.consecutive_failures + 1)

    detected_at = utc_now()
    latest = _latest_history(db, product_id)
    if _should_record(latest, scraped, now):
        _insert_history(db, product, scraped, now)

    updated = replace(
        product,
        current_price=scraped["price"],
        last_checked_at=now,
        consecutive_failures=0,
    )
    db.products.update_one(
        {"_id": product_id},
        {
            "$set": {
                "current_price": to_decimal128(updated.current_price),
                "last_checked_at": now,
                "consecutive_failures": 0,
            }
        },
    )

    if updated.current_price < product.current_price:
        _notify_price_drop(
            db, updated, product.current_price, detected_at, now, alert_dispatcher
        )
    return updated


def get_history(
    product_id: ObjectId | str,
    days: int = LOW_PRICE_WINDOW_DAYS,
    *,
    db: Database | None = None,
    now: datetime | None = None,
) -> HistorySummary:
    """Price points from the last `days` days, oldest first, with min/max/current.

    `current_price` is the most recent point in the window; all prices are None
    when the window has no points.
    """
    if isinstance(days, bool) or not isinstance(days, int) or days <= 0:
        raise ValueError("days must be a positive integer")

    db = db if db is not None else get_db()
    now = now or utc_now()

    rows = db.price_history.find(
        {
            "product_id": validate_object_id(product_id),
            "scraped_at": {"$gte": now - timedelta(days=days)},
        }
    ).sort("scraped_at", 1)
    points = [PriceHistory.from_document(row) for row in rows]

    if not points:
        return HistorySummary(
            points=[], min_price=None, max_price=None, current_price=None
        )

    prices = [point.price for point in points]
    return HistorySummary(
        points=points,
        min_price=min(prices),
        max_price=max(prices),
        current_price=points[-1].price,
    )


def is_30d_low(
    product: Product,
    *,
    db: Database | None = None,
    now: datetime | None = None,
) -> bool:
    """True if the current price is <= the lowest price of the last 30 days.

    The latest observation is excluded from the comparison. With no earlier
    observation in the window there is nothing to compare against, so the
    result is False.
    """
    db = db if db is not None else get_db()
    now = now or utc_now()
    product_id = _require_id(product)

    latest = _latest_history(db, product_id)
    query = {
        "product_id": product_id,
        "scraped_at": {"$gte": now - timedelta(days=LOW_PRICE_WINDOW_DAYS)},
    }
    if latest is not None:
        query["_id"] = {"$ne": latest._id}

    prior_prices = [
        PriceHistory.from_document(row).price for row in db.price_history.find(query)
    ]
    if not prior_prices:
        return False

    return product.current_price <= min(prior_prices)


def _notify_price_drop(
    db: Database,
    product: Product,
    old_price: Decimal,
    detected_at: datetime,
    now: datetime,
    dispatcher,
) -> None:
    # Imported here: the alert engine imports this module for is_30d_low.
    from app.services.alerts import process_price_drop

    try:
        process_price_drop(
            db,
            product,
            old_price,
            detected_at=detected_at,
            now=now,
            dispatcher=dispatcher,
        )
    except Exception:
        # A broken alert must never lose the price we just recorded.
        logger.exception("Alert processing failed for %s", product.url)


def _should_record(
    latest: PriceHistory | None, scraped: ScrapedProduct, now: datetime
) -> bool:
    if latest is None:
        return True
    return (
        scraped["price"] != latest.price
        or scraped["in_stock"] != latest.in_stock
        or now - latest.scraped_at > HEARTBEAT_INTERVAL
    )


def _latest_history(db: Database, product_id: ObjectId) -> PriceHistory | None:
    row = db.price_history.find_one(
        {"product_id": product_id}, sort=[("scraped_at", -1)]
    )
    return PriceHistory.from_document(row) if row is not None else None


def _insert_history(
    db: Database, product: Product, scraped: ScrapedProduct, now: datetime
) -> None:
    observation = PriceHistory(
        product_id=product._id,
        price=scraped["price"],
        in_stock=scraped["in_stock"],
        scraped_at=now,
    )
    db.price_history.insert_one(observation.to_document())


def _require_id(product: Product) -> ObjectId:
    if product._id is None:
        raise ValueError("product must be saved before it can be tracked")
    return product._id

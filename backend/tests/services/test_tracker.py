from datetime import datetime, timedelta, timezone
from decimal import Decimal

import mongomock
import pytest

from app.models import PriceHistory, Product, Store, init_db
from app.scrapers import ScraperError
from app.services import tracker

URL = "https://www.flipkart.com/item/p/1"
T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


class FakeScraper:
    store = Store.FLIPKART

    def __init__(self, price="1000.00", in_stock=True, error=None):
        self.price = Decimal(price)
        self.in_stock = in_stock
        self.error = error
        self.fetch_calls = 0

    def fetch(self, url):
        self.fetch_calls += 1
        if self.error:
            raise self.error
        return "<html></html>"

    def parse(self, html):
        return {
            "title": "Test Headphones",
            "price": self.price,
            "image_url": "https://cdn.example.com/p.jpg",
            "in_stock": self.in_stock,
        }


@pytest.fixture
def db():
    database = mongomock.MongoClient(tz_aware=True).pricescope_test
    init_db(database)
    return database


def history_rows(db, product):
    return list(db.price_history.find({"product_id": product._id}).sort("scraped_at", 1))


def add_at(db, price, when=T0, **kwargs):
    return tracker.add_product(
        URL, db=db, scraper=FakeScraper(price, **kwargs), now=when
    )


def seed_history(db, product, prices_by_days_ago, now=T0):
    for days_ago, price in prices_by_days_ago:
        db.price_history.insert_one(
            PriceHistory(
                product_id=product._id,
                price=price,
                in_stock=True,
                scraped_at=now - timedelta(days=days_ago),
            ).to_document()
        )


def test_add_product_creates_product_and_first_history_row(db):
    product = add_at(db, "1000")

    assert product._id is not None
    assert product.store is Store.FLIPKART
    assert product.title == "Test Headphones"
    assert product.current_price == Decimal("1000.00")
    assert product.consecutive_failures == 0

    stored = Product.from_document(db.products.find_one({"url": URL}))
    assert stored == product

    rows = history_rows(db, product)
    assert len(rows) == 1
    assert PriceHistory.from_document(rows[0]).price == Decimal("1000.00")
    assert rows[0]["in_stock"] is True


def test_add_product_detects_store_from_url_when_no_scraper_given(db):
    with pytest.raises(ScraperError, match="No scraper registered"):
        tracker.add_product("https://www.amazon.in/item", db=db)

    assert db.products.count_documents({}) == 0


def test_add_product_failure_stores_nothing(db):
    scraper = FakeScraper(error=ScraperError("boom"))

    with pytest.raises(ScraperError):
        tracker.add_product(URL, db=db, scraper=scraper, now=T0)

    assert db.products.count_documents({}) == 0
    assert db.price_history.count_documents({}) == 0


def test_add_product_twice_does_not_duplicate(db):
    first = add_at(db, "1000")
    second = add_at(db, "1000", when=T0 + timedelta(hours=1))

    assert second._id == first._id
    assert db.products.count_documents({}) == 1
    assert len(history_rows(db, first)) == 1


def test_unchanged_price_adds_no_history_row(db):
    product = add_at(db, "1000")
    later = T0 + timedelta(hours=2)

    updated = tracker.record_price(
        product, db=db, scraper=FakeScraper("1000"), now=later
    )

    assert len(history_rows(db, product)) == 1
    assert updated.last_checked_at == later
    assert db.products.find_one({"_id": product._id})["last_checked_at"] == later


def test_price_drop_adds_history_row_and_updates_product(db):
    product = add_at(db, "1000")

    updated = tracker.record_price(
        product, db=db, scraper=FakeScraper("899.50"), now=T0 + timedelta(hours=2)
    )

    assert updated.current_price == Decimal("899.50")
    stored = Product.from_document(db.products.find_one({"_id": product._id}))
    assert stored.current_price == Decimal("899.50")
    prices = [PriceHistory.from_document(r).price for r in history_rows(db, product)]
    assert prices == [Decimal("1000.00"), Decimal("899.50")]


def test_price_rise_adds_history_row(db):
    product = add_at(db, "1000")

    tracker.record_price(
        product, db=db, scraper=FakeScraper("1250"), now=T0 + timedelta(hours=2)
    )

    prices = [PriceHistory.from_document(r).price for r in history_rows(db, product)]
    assert prices == [Decimal("1000.00"), Decimal("1250.00")]


def test_stock_change_adds_history_row_even_if_price_same(db):
    product = add_at(db, "1000")

    tracker.record_price(
        product,
        db=db,
        scraper=FakeScraper("1000", in_stock=False),
        now=T0 + timedelta(hours=2),
    )

    rows = history_rows(db, product)
    assert [r["in_stock"] for r in rows] == [True, False]


def test_unchanged_price_adds_row_after_24_hours(db):
    product = add_at(db, "1000")

    tracker.record_price(
        product, db=db, scraper=FakeScraper("1000"), now=T0 + timedelta(hours=24)
    )
    assert len(history_rows(db, product)) == 1

    tracker.record_price(
        product,
        db=db,
        scraper=FakeScraper("1000"),
        now=T0 + timedelta(hours=24, minutes=1),
    )
    assert len(history_rows(db, product)) == 2


def test_scraper_failure_keeps_old_data_and_counts_failures(db, caplog):
    product = add_at(db, "1000")
    failing = FakeScraper(error=ScraperError("blocked"))

    with caplog.at_level("WARNING"):
        first = tracker.record_price(
            product, db=db, scraper=failing, now=T0 + timedelta(hours=1)
        )
        second = tracker.record_price(
            first, db=db, scraper=failing, now=T0 + timedelta(hours=2)
        )

    assert "Scrape failed" in caplog.text
    assert (first.consecutive_failures, second.consecutive_failures) == (1, 2)
    assert second.current_price == Decimal("1000.00")
    assert second.last_checked_at == T0

    stored = Product.from_document(db.products.find_one({"_id": product._id}))
    assert stored.consecutive_failures == 2
    assert stored.current_price == Decimal("1000.00")
    assert stored.last_checked_at == T0
    assert len(history_rows(db, product)) == 1


def test_unexpected_scraper_exception_is_also_handled(db):
    product = add_at(db, "1000")

    updated = tracker.record_price(
        product,
        db=db,
        scraper=FakeScraper(error=RuntimeError("parser bug")),
        now=T0 + timedelta(hours=1),
    )

    assert updated.consecutive_failures == 1


def test_successful_scrape_resets_failure_counter(db):
    product = add_at(db, "1000")
    failed = tracker.record_price(
        product,
        db=db,
        scraper=FakeScraper(error=ScraperError("blocked")),
        now=T0 + timedelta(hours=1),
    )

    recovered = tracker.record_price(
        failed, db=db, scraper=FakeScraper("1000"), now=T0 + timedelta(hours=2)
    )

    assert recovered.consecutive_failures == 0
    assert db.products.find_one({"_id": product._id})["consecutive_failures"] == 0


def test_get_history_returns_sorted_points_with_stats(db):
    product = add_at(db, "1000", when=T0 - timedelta(days=10))
    seed_history(db, product, [(2, "700"), (5, "1200"), (40, "50")])

    summary = tracker.get_history(product._id, 30, db=db, now=T0)

    assert [p.price for p in summary.points] == [
        Decimal("1000.00"),
        Decimal("1200.00"),
        Decimal("700.00"),
    ]
    assert summary.points == sorted(summary.points, key=lambda p: p.scraped_at)
    assert summary.min_price == Decimal("700.00")
    assert summary.max_price == Decimal("1200.00")
    assert summary.current_price == Decimal("700.00")


def test_get_history_respects_window_and_handles_empty(db):
    product = add_at(db, "1000", when=T0 - timedelta(days=20))

    narrow = tracker.get_history(product._id, 7, db=db, now=T0)
    assert narrow.points == []
    assert narrow.min_price is None
    assert narrow.max_price is None
    assert narrow.current_price is None

    wide = tracker.get_history(str(product._id), 30, db=db, now=T0)
    assert len(wide.points) == 1


@pytest.mark.parametrize("days", [0, -1, True, "7"])
def test_get_history_rejects_invalid_days(db, days):
    with pytest.raises(ValueError, match="days"):
        tracker.get_history("65a000000000000000000000", days, db=db)


def test_is_30d_low_true_when_price_at_or_below_prior_low(db):
    product = add_at(db, "1000", when=T0 - timedelta(days=20))
    seed_history(db, product, [(10, "900")])
    current = tracker.record_price(
        product, db=db, scraper=FakeScraper("850"), now=T0
    )

    assert tracker.is_30d_low(current, db=db, now=T0) is True


def test_is_30d_low_true_when_equal_to_prior_low(db):
    product = add_at(db, "900", when=T0 - timedelta(days=20))
    seed_history(db, product, [(10, "1100")])
    current = tracker.record_price(
        product, db=db, scraper=FakeScraper("900"), now=T0
    )

    assert tracker.is_30d_low(current, db=db, now=T0) is True


def test_is_30d_low_false_when_cheaper_price_exists_in_window(db):
    product = add_at(db, "1000", when=T0 - timedelta(days=20))
    seed_history(db, product, [(10, "800")])
    current = tracker.record_price(
        product, db=db, scraper=FakeScraper("950"), now=T0
    )

    assert tracker.is_30d_low(current, db=db, now=T0) is False


def test_is_30d_low_ignores_prices_older_than_30_days(db):
    product = add_at(db, "1000", when=T0 - timedelta(days=20))
    seed_history(db, product, [(45, "500")])
    current = tracker.record_price(
        product, db=db, scraper=FakeScraper("950"), now=T0
    )

    assert tracker.is_30d_low(current, db=db, now=T0) is True


def test_is_30d_low_false_without_earlier_observations(db):
    product = add_at(db, "1000", when=T0)

    assert tracker.is_30d_low(product, db=db, now=T0) is False


def test_record_price_requires_saved_product(db):
    unsaved = Product(
        store="flipkart",
        url=URL,
        title="x",
        image_url="https://cdn.example.com/p.jpg",
        current_price="10",
    )

    with pytest.raises(ValueError, match="saved"):
        tracker.record_price(unsaved, db=db, scraper=FakeScraper())

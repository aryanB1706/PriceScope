import threading
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import mongomock
import pytest

from app import create_app
from app.jobs import scheduler as scheduler_module
from app.jobs.scheduler import (
    JOB_ID,
    StoreThrottle,
    acquire_scheduler_lock,
    build_scheduler,
    run_scrape_job,
)
from app.models import PriceHistory, Product, Store, Watch, init_db
from app.scrapers import ScraperError

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


class FakeScraper:
    def __init__(self, store, price, in_stock=True, error=None, tracker=None):
        self.store = store
        self.price = Decimal(price)
        self.in_stock = in_stock
        self.error = error
        self.tracker = tracker

    def fetch(self, url):
        if self.tracker:
            self.tracker.enter()
        if self.error:
            raise self.error
        return "<html></html>"

    def parse(self, html):
        try:
            return {
                "title": "Item",
                "price": self.price,
                "image_url": "https://cdn.example.com/i.jpg",
                "in_stock": self.in_stock,
            }
        finally:
            if self.tracker:
                self.tracker.leave()


class ConcurrencyTracker:
    def __init__(self):
        self._lock = threading.Lock()
        self.current = 0
        self.peak = 0

    def enter(self):
        with self._lock:
            self.current += 1
            self.peak = max(self.peak, self.current)
        time.sleep(0.02)

    def leave(self):
        with self._lock:
            self.current -= 1


@pytest.fixture
def db():
    database = mongomock.MongoClient(tz_aware=True).pricescope_test
    init_db(database)
    return database


def add_product(db, name, price="1000", store="flipkart", watched=True, watchers=1):
    product = Product(
        store=store,
        url=f"https://www.{store}.com/{name}",
        title=name,
        image_url="https://cdn.example.com/i.jpg",
        current_price=price,
        last_checked_at=T0,
        created_at=T0,
    )
    product_id = db.products.insert_one(product.to_document()).inserted_id
    db.price_history.insert_one(
        PriceHistory(
            product_id=product_id, price=price, in_stock=True, scraped_at=T0
        ).to_document()
    )
    if watched:
        for index in range(watchers):
            db.watches.insert_one(
                Watch(user_id=f"user-{name}-{index}", product_id=product_id).to_document()
            )
    return product_id


def factory_from(behaviours):
    """Build a scraper factory keyed by product title."""

    def factory(product):
        behaviour = behaviours[product.title]
        if isinstance(behaviour, Exception):
            raise behaviour
        return behaviour

    return factory


def run(db, behaviours, **kwargs):
    return run_scrape_job(
        db,
        scraper_factory=factory_from(behaviours),
        store_delay=0,
        **kwargs,
    )


def test_summary_counts_are_correct(db):
    add_product(db, "same", "1000")
    add_product(db, "drop", "1000")
    add_product(db, "rise", "500")
    add_product(db, "broken", "700")
    add_product(db, "unwatched", "300", watched=False)

    summary = run(
        db,
        {
            "same": FakeScraper(Store.FLIPKART, "1000"),
            "drop": FakeScraper(Store.FLIPKART, "900"),
            "rise": FakeScraper(Store.FLIPKART, "650"),
            "broken": FakeScraper(Store.FLIPKART, "700", error=ScraperError("blocked")),
        },
    )

    assert summary.products_checked == 4
    assert summary.succeeded == 3
    assert summary.failed == 1
    assert summary.price_changes == 2
    assert summary.trigger == "scheduled"
    assert summary.duration_seconds >= 0


def test_product_watched_by_many_users_is_checked_once(db):
    add_product(db, "popular", "1000", watchers=3)

    summary = run(db, {"popular": FakeScraper(Store.FLIPKART, "1000")})

    assert summary.products_checked == 1


def test_one_failure_does_not_stop_the_run(db):
    ids = {name: add_product(db, name) for name in ["a", "bad", "c", "d"]}

    summary = run(
        db,
        {
            "a": FakeScraper(Store.FLIPKART, "800"),
            "bad": FakeScraper(Store.FLIPKART, "1", error=ScraperError("boom")),
            "c": FakeScraper(Store.FLIPKART, "800"),
            "d": FakeScraper(Store.FLIPKART, "800"),
        },
        max_workers=1,
    )

    assert (summary.succeeded, summary.failed) == (3, 1)
    for name in ["a", "c", "d"]:
        stored = db.products.find_one({"_id": ids[name]})
        assert stored["consecutive_failures"] == 0
        assert Product.from_document(stored).current_price == Decimal("800.00")
    assert db.products.find_one({"_id": ids["bad"]})["consecutive_failures"] == 1


def test_unexpected_errors_are_counted_as_failures(db):
    add_product(db, "factory-error")
    add_product(db, "parser-bug")
    add_product(db, "fine")

    summary = run(
        db,
        {
            "factory-error": RuntimeError("no scraper"),
            "parser-bug": FakeScraper(
                Store.FLIPKART, "1", error=RuntimeError("parser bug")
            ),
            "fine": FakeScraper(Store.FLIPKART, "1000"),
        },
    )

    assert (summary.products_checked, summary.succeeded, summary.failed) == (3, 1, 2)


def test_corrupt_product_document_counts_as_failure(db):
    add_product(db, "fine")
    bad_id = db.products.insert_one({"url": "not-a-product"}).inserted_id
    db.watches.insert_one({"user_id": "u", "product_id": bad_id})

    summary = run(db, {"fine": FakeScraper(Store.FLIPKART, "1000")})

    assert (summary.products_checked, summary.succeeded, summary.failed) == (2, 1, 1)


def test_run_summary_is_stored_in_job_runs(db):
    add_product(db, "drop", "1000")
    add_product(db, "broken", "1000")

    summary = run(
        db,
        {
            "drop": FakeScraper(Store.FLIPKART, "900"),
            "broken": FakeScraper(Store.FLIPKART, "1", error=ScraperError("x")),
        },
        trigger="manual",
    )

    stored = db.job_runs.find_one({})
    assert db.job_runs.count_documents({}) == 1
    assert stored["trigger"] == "manual"
    assert stored["products_checked"] == 2
    assert stored["succeeded"] == 1
    assert stored["failed"] == 1
    assert stored["price_changes"] == 1
    assert stored["duration_seconds"] == summary.duration_seconds
    assert stored["finished_at"] >= stored["started_at"]


def test_run_logs_summary(db, caplog):
    add_product(db, "drop", "1000")

    with caplog.at_level("INFO", logger="app.jobs.scheduler"):
        run(db, {"drop": FakeScraper(Store.FLIPKART, "900")})

    assert "checked=1 succeeded=1 failed=0 price_changes=1" in caplog.text


def test_run_with_no_watched_products_still_records_a_run(db):
    add_product(db, "unwatched", watched=False)

    summary = run(db, {})

    assert (summary.products_checked, summary.succeeded, summary.failed) == (0, 0, 0)
    assert db.job_runs.count_documents({}) == 1


def test_run_survives_job_runs_write_failure(db, monkeypatch):
    add_product(db, "drop", "1000")

    def explode(document):
        raise RuntimeError("mongo down")

    monkeypatch.setattr(db.job_runs, "insert_one", explode)

    summary = run(db, {"drop": FakeScraper(Store.FLIPKART, "900")})

    assert summary.succeeded == 1


def test_concurrency_never_exceeds_max_workers(db):
    tracker = ConcurrencyTracker()
    behaviours = {}
    for index in range(10):
        name = f"item-{index}"
        add_product(db, name)
        behaviours[name] = FakeScraper(Store.FLIPKART, "1000", tracker=tracker)

    summary = run(db, behaviours, max_workers=3)

    assert summary.succeeded == 10
    assert 1 < tracker.peak <= 3


def test_run_rejects_invalid_worker_count(db):
    with pytest.raises(ValueError, match="max_workers"):
        run_scrape_job(db, max_workers=0)


def test_store_throttle_spaces_requests_per_store():
    now = [100.0]
    sleeps = []

    def sleeper(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    throttle = StoreThrottle(2.0, clock=lambda: now[0], sleeper=sleeper)

    throttle.wait("flipkart")
    throttle.wait("myntra")  # different store: no wait
    assert sleeps == []

    now[0] += 0.5
    throttle.wait("flipkart")
    assert sleeps == [pytest.approx(1.5)]

    now[0] += 5
    throttle.wait("flipkart")  # already past the delay
    assert len(sleeps) == 1


def test_build_scheduler_registers_one_interval_job(db):
    scheduler = build_scheduler(db, 6)

    job = scheduler.get_job(JOB_ID)
    assert len(scheduler.get_jobs()) == 1
    assert job.trigger.interval == timedelta(hours=6)
    assert job.max_instances == 1
    assert job.coalesce is True
    assert job.misfire_grace_time == 15 * 60


@pytest.mark.parametrize("hours", [0, -1])
def test_build_scheduler_rejects_non_positive_interval(db, hours):
    with pytest.raises(ValueError, match="SCRAPE_INTERVAL_HOURS"):
        build_scheduler(db, hours)


def test_lock_can_only_be_held_once(tmp_path):
    path = str(tmp_path / "scheduler.lock")

    first = acquire_scheduler_lock(path)
    second = acquire_scheduler_lock(path)
    assert first is not None
    assert second is None

    first.close()
    third = acquire_scheduler_lock(path)
    assert third is not None
    third.close()


@pytest.fixture
def scheduler_app(tmp_path, monkeypatch):
    monkeypatch.delenv("WERKZEUG_RUN_MAIN", raising=False)
    started = []

    class StubScheduler:
        def start(self):
            started.append(self)

        def shutdown(self, wait=False):
            pass

    monkeypatch.setattr(
        scheduler_module, "build_scheduler", lambda db, hours: StubScheduler()
    )

    def make(**config):
        return create_app(
            {
                "TESTING": True,
                "DEBUG": False,
                "SCHEDULER_ENABLED": True,
                "SCHEDULER_LOCK_PATH": str(tmp_path / "scheduler.lock"),
                **config,
            }
        ), started

    return make


def test_scheduler_is_disabled_by_default(scheduler_app):
    app, started = scheduler_app(SCHEDULER_ENABLED=False)

    assert started == []
    assert "scheduler" not in app.extensions


def test_only_first_app_instance_starts_the_scheduler(scheduler_app):
    first, started = scheduler_app()
    second, _ = scheduler_app()

    assert len(started) == 1
    assert "scheduler" in first.extensions
    assert "scheduler" not in second.extensions


def test_reloader_parent_process_does_not_start_scheduler(scheduler_app, monkeypatch):
    app, started = scheduler_app(DEBUG=True)
    assert started == []

    monkeypatch.setenv("WERKZEUG_RUN_MAIN", "true")
    child, started = scheduler_app(DEBUG=True)
    assert len(started) == 1
    assert "scheduler" in child.extensions

import atexit
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from flask import Flask
from pymongo.database import Database

from app.db import get_db
from app.models import Product
from app.models.validation import utc_now
from app.scrapers import BaseScraper
from app.services.tracker import record_price

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX platforms
    fcntl = None

logger = logging.getLogger(__name__)

JOB_ID = "scrape_products"
DEFAULT_MAX_WORKERS = 3
DEFAULT_STORE_DELAY = 2.0
MISFIRE_GRACE_SECONDS = 15 * 60


@dataclass(frozen=True, slots=True)
class RunSummary:
    trigger: str
    started_at: datetime
    finished_at: datetime
    duration_seconds: float
    products_checked: int
    succeeded: int
    failed: int
    price_changes: int

    def to_document(self) -> dict:
        return {
            "trigger": self.trigger,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "products_checked": self.products_checked,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "price_changes": self.price_changes,
        }


class StoreThrottle:
    """Keeps requests to the same store at least `delay` seconds apart.

    Different stores do not wait on each other, so the worker pool can still
    scrape Flipkart, Myntra and Croma in parallel.
    """

    def __init__(self, delay: float, clock=time.monotonic, sleeper=time.sleep):
        self._delay = delay
        self._clock = clock
        self._sleep = sleeper
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._last_start: dict[str, float] = {}

    def wait(self, store: str) -> None:
        with self._guard:
            lock = self._locks.setdefault(store, threading.Lock())

        with lock:
            last = self._last_start.get(store)
            if last is not None:
                remaining = self._delay - (self._clock() - last)
                if remaining > 0:
                    self._sleep(remaining)
            self._last_start[store] = self._clock()


def run_scrape_job(
    db: Database,
    *,
    trigger: str = "scheduled",
    max_workers: int = DEFAULT_MAX_WORKERS,
    store_delay: float = DEFAULT_STORE_DELAY,
    scraper_factory: Callable[[Product], BaseScraper] | None = None,
    throttle: StoreThrottle | None = None,
) -> RunSummary:
    """Refresh every product that has at least one watch.

    One product failing never stops the run; it is counted as failed. The
    summary is logged and stored in the job_runs collection.
    """
    if max_workers < 1:
        raise ValueError("max_workers must be at least 1")

    started_at = utc_now()
    started = time.monotonic()
    throttle = throttle or StoreThrottle(store_delay)

    watched_ids = db.watches.distinct("product_id")
    documents = list(db.products.find({"_id": {"$in": watched_ids}}))

    def refresh(document: dict) -> str:
        try:
            product = Product.from_document(document)
            throttle.wait(product.store.value)
            scraper = scraper_factory(product) if scraper_factory else None
            updated = record_price(product, db=db, scraper=scraper)
        except Exception:
            logger.exception("Refresh failed for product %s", document.get("_id"))
            return "failed"

        # record_price swallows scrape errors and bumps the failure counter;
        # a successful scrape always resets it to zero.
        if updated.consecutive_failures > 0:
            return "failed"
        if updated.current_price != product.current_price:
            return "changed"
        return "ok"

    with ThreadPoolExecutor(
        max_workers=max_workers, thread_name_prefix="scrape"
    ) as pool:
        outcomes = list(pool.map(refresh, documents))

    failed = outcomes.count("failed")
    summary = RunSummary(
        trigger=trigger,
        started_at=started_at,
        finished_at=utc_now(),
        duration_seconds=round(time.monotonic() - started, 3),
        products_checked=len(outcomes),
        succeeded=len(outcomes) - failed,
        failed=failed,
        price_changes=outcomes.count("changed"),
    )

    logger.info(
        "Scrape run finished (%s): checked=%d succeeded=%d failed=%d "
        "price_changes=%d duration=%.1fs",
        summary.trigger,
        summary.products_checked,
        summary.succeeded,
        summary.failed,
        summary.price_changes,
        summary.duration_seconds,
    )
    try:
        db.job_runs.insert_one(summary.to_document())
    except Exception:
        logger.exception("Could not store job run summary")

    return summary


def build_scheduler(db: Database, interval_hours: float) -> BackgroundScheduler:
    """Create (but do not start) a scheduler with the periodic scrape job."""
    if interval_hours <= 0:
        raise ValueError("SCRAPE_INTERVAL_HOURS must be greater than zero")

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        run_scrape_job,
        IntervalTrigger(hours=interval_hours),
        args=[db],
        id=JOB_ID,
        name="Scrape watched products",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=MISFIRE_GRACE_SECONDS,
    )
    return scheduler


def acquire_scheduler_lock(path: str):
    """Take an exclusive, non-blocking lock; return the open file or None.

    The OS releases the lock when the holding process exits or crashes, so
    another process (for example a restarted gunicorn worker) can take over.
    """
    if fcntl is None:
        logger.warning("fcntl unavailable; cannot guard against duplicate schedulers")
        return open(path, "a")

    handle = open(path, "a")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def init_scheduler(app: Flask) -> BackgroundScheduler | None:
    """Start the background scheduler in this process, at most once per host."""
    if not app.config.get("SCHEDULER_ENABLED"):
        return None

    # `flask run --debug` runs the app in a reloader child (WERKZEUG_RUN_MAIN)
    # and a watcher parent; only the child serves requests.
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        logger.info("Scheduler not started in the reloader parent process")
        return None

    lock = acquire_scheduler_lock(app.config["SCHEDULER_LOCK_PATH"])
    if lock is None:
        logger.info("Scheduler already running in another process; not starting")
        return None

    with app.app_context():
        db = get_db()
    scheduler = build_scheduler(db, app.config["SCRAPE_INTERVAL_HOURS"])
    scheduler.start()

    # Keep a reference: closing the file would release the lock.
    app.extensions["scheduler"] = scheduler
    app.extensions["scheduler_lock"] = lock
    atexit.register(lambda: scheduler.shutdown(wait=False))

    logger.info(
        "Scheduler started: scraping every %s hours", app.config["SCRAPE_INTERVAL_HOURS"]
    )
    return scheduler

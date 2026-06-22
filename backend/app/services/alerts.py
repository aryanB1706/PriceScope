import atexit
import logging
import queue
import smtplib
import ssl
import threading
import time
from datetime import datetime, timedelta
from decimal import Decimal
from email.message import EmailMessage
from typing import Callable

from flask import Flask
from pymongo.database import Database

from app.db import get_db
from app.models import Alert, AlertReason, EmailStatus, Product, Watch
from app.models.validation import utc_now
from app.services.alert_email import AlertEmailJob, render_alert_email
from app.services.auth import make_email_lookup

logger = logging.getLogger(__name__)

DUPLICATE_WINDOW = timedelta(hours=24)
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 2.0
NOT_CONFIGURED_ERROR = "Email delivery is not configured (SMTP_HOST is empty)"


class PermanentEmailError(Exception):
    """A delivery failure that retrying cannot fix (for example no recipient)."""


class SmtpEmailSender:
    def __init__(
        self,
        host: str,
        port: int = 587,
        username: str = "",
        password: str = "",
        from_addr: str = "",
        security: str = "starttls",
        timeout: float = 15.0,
        smtp_factory=None,
    ):
        if security not in {"starttls", "ssl", "none"}:
            raise ValueError("SMTP_SECURITY must be one of: starttls, ssl, none")

        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_addr = from_addr or username
        self.security = security
        self.timeout = timeout
        self._smtp_factory = smtp_factory

    def send(self, to_addr: str, subject: str, text: str, html: str) -> None:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.from_addr
        message["To"] = to_addr
        message.set_content(text)
        message.add_alternative(html, subtype="html")

        factory = self._smtp_factory or (
            smtplib.SMTP_SSL if self.security == "ssl" else smtplib.SMTP
        )
        with factory(self.host, self.port, timeout=self.timeout) as server:
            if self.security == "starttls":
                server.starttls(context=ssl.create_default_context())
            if self.username:
                server.login(self.username, self.password)
            server.send_message(message)


class AlertDispatcher:
    """Sends alert emails on a background thread so scraping never waits on SMTP."""

    def __init__(
        self,
        db: Database,
        sender,
        email_lookup: Callable[[str], str | None],
        *,
        max_attempts: int = MAX_ATTEMPTS,
        backoff_seconds: float = BACKOFF_SECONDS,
        sleeper=time.sleep,
        clock=utc_now,
    ):
        self._db = db
        self._sender = sender
        self._lookup = email_lookup
        self._max_attempts = max_attempts
        self._backoff = backoff_seconds
        self._sleep = sleeper
        self._clock = clock
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._thread_lock = threading.Lock()

    def submit(self, job: AlertEmailJob) -> None:
        self._ensure_worker()
        self._queue.put(job)

    def join(self) -> None:
        """Block until every queued email has been delivered or has failed."""
        self._queue.join()

    def shutdown(self, timeout: float = 30.0) -> None:
        thread = self._thread
        if thread is None or not thread.is_alive():
            return
        self._queue.put(None)
        thread.join(timeout)

    def _ensure_worker(self) -> None:
        with self._thread_lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run, name="alert-email", daemon=True
                )
                self._thread.start()

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            try:
                if job is None:
                    return
                self.deliver(job)
            except Exception:
                logger.exception("Unexpected error delivering alert email")
            finally:
                self._queue.task_done()

    def deliver(self, job: AlertEmailJob) -> None:
        """Send one alert, retrying with exponential backoff, and record the result."""
        recipient: str | None = None
        last_error: Exception | None = None
        attempt = 0

        while attempt < self._max_attempts:
            attempt += 1
            self._db.alerts.update_one(
                {"_id": job.alert_id}, {"$set": {"attempts": attempt}}
            )

            try:
                if recipient is None:
                    recipient = self._lookup(job.user_id)
                    if not recipient:
                        raise PermanentEmailError("User has no email address")
                subject, text, html = render_alert_email(job)
                self._sender.send(recipient, subject, text, html)
            except PermanentEmailError as exc:
                last_error = exc
                break
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Alert email attempt %d/%d failed for alert %s: %s",
                    attempt,
                    self._max_attempts,
                    job.alert_id,
                    exc,
                )
                if attempt < self._max_attempts:
                    self._sleep(self._backoff * 2 ** (attempt - 1))
            else:
                self._mark_sent(job)
                return

        self._mark_failed(job, last_error)

    def _mark_sent(self, job: AlertEmailJob) -> None:
        sent_at = self._clock()
        latency_ms = round((sent_at - job.detected_at).total_seconds() * 1000, 1)
        self._db.alerts.update_one(
            {"_id": job.alert_id},
            {
                "$set": {
                    "email_status": EmailStatus.SENT.value,
                    "sent_at": sent_at,
                    "latency_ms": max(latency_ms, 0.0),
                    "error": None,
                }
            },
        )

    def _mark_failed(self, job: AlertEmailJob, error: Exception | None) -> None:
        message = f"{type(error).__name__}: {error}" if error else "Unknown error"
        logger.error("Alert email %s failed permanently: %s", job.alert_id, message)
        self._db.alerts.update_one(
            {"_id": job.alert_id},
            {
                "$set": {
                    "email_status": EmailStatus.FAILED.value,
                    "error": message[:500],
                }
            },
        )


_default_dispatcher: AlertDispatcher | None = None


def set_default_dispatcher(dispatcher: AlertDispatcher | None) -> None:
    global _default_dispatcher
    _default_dispatcher = dispatcher


def get_default_dispatcher() -> AlertDispatcher | None:
    return _default_dispatcher


def init_alerts(app: Flask) -> AlertDispatcher | None:
    """Configure the process-wide dispatcher from SMTP settings, if present."""
    if not app.config.get("SMTP_HOST"):
        set_default_dispatcher(None)
        return None

    with app.app_context():
        db = get_db()
    sender = SmtpEmailSender(
        host=app.config["SMTP_HOST"],
        port=app.config["SMTP_PORT"],
        username=app.config["SMTP_USERNAME"],
        password=app.config["SMTP_PASSWORD"],
        from_addr=app.config["SMTP_FROM"],
        security=app.config["SMTP_SECURITY"],
    )
    dispatcher = AlertDispatcher(
        db, sender, make_email_lookup(app.config["FIREBASE_CREDENTIALS_PATH"])
    )
    set_default_dispatcher(dispatcher)
    # Let queued emails finish before a short-lived process (flask scrape-now) exits.
    atexit.register(dispatcher.shutdown)
    return dispatcher


def process_price_drop(
    db: Database,
    product: Product,
    old_price: Decimal,
    *,
    detected_at: datetime | None = None,
    now: datetime | None = None,
    dispatcher: AlertDispatcher | None = None,
) -> list[Alert]:
    """Create and queue alerts for watches that the new (lower) price satisfies.

    `detected_at` is when the drop was seen (the start of the latency clock);
    `now` is the clock used for the 30-day-low window.
    """
    detected_at = detected_at or utc_now()
    dispatcher = dispatcher or get_default_dispatcher()
    new_price = product.current_price
    if new_price >= old_price:
        return []

    watches = [Watch.from_document(doc) for doc in db.watches.find({"product_id": product._id})]
    if not watches:
        return []

    is_low: bool | None = None
    alerts: list[Alert] = []

    for watch in watches:
        reason = None
        if watch.target_price is not None and new_price <= watch.target_price:
            reason = AlertReason.TARGET_PRICE
        elif watch.alert_on_30d_low:
            if is_low is None:
                # Imported here: tracker imports this module to fire alerts.
                from app.services.tracker import is_30d_low

                is_low = is_30d_low(product, db=db, now=now)
            if is_low:
                reason = AlertReason.THIRTY_DAY_LOW

        if reason is None or _is_duplicate(db, watch.user_id, product, detected_at):
            continue

        alerts.append(
            _create_alert(db, watch, product, old_price, reason, detected_at, dispatcher)
        )

    return alerts


def _is_duplicate(
    db: Database, user_id: str, product: Product, detected_at: datetime
) -> bool:
    """Apply the anti-spam rules against the user's latest live alert for the product.

    Failed alerts never reached the user, so they do not suppress new ones.
    """
    document = db.alerts.find_one(
        {
            "user_id": user_id,
            "product_id": product._id,
            "email_status": {
                "$in": [EmailStatus.PENDING.value, EmailStatus.SENT.value]
            },
        },
        sort=[("detected_at", -1)],
    )
    if document is None:
        return False

    last = Alert.from_document(document)
    if last.new_price == product.current_price:
        return True
    within_window = detected_at - last.detected_at < DUPLICATE_WINDOW
    return within_window and product.current_price >= last.new_price


def _create_alert(
    db: Database,
    watch: Watch,
    product: Product,
    old_price: Decimal,
    reason: AlertReason,
    detected_at: datetime,
    dispatcher: AlertDispatcher | None,
) -> Alert:
    unconfigured = dispatcher is None
    alert = Alert(
        user_id=watch.user_id,
        product_id=product._id,
        reason=reason,
        old_price=old_price,
        new_price=product.current_price,
        detected_at=detected_at,
        email_status=EmailStatus.FAILED if unconfigured else EmailStatus.PENDING,
        error=NOT_CONFIGURED_ERROR if unconfigured else None,
    )
    alert_id = db.alerts.insert_one(alert.to_document()).inserted_id
    db.watches.update_one(
        {"_id": watch._id}, {"$set": {"last_alerted_at": detected_at}}
    )

    if unconfigured:
        logger.warning("Alert for %s not emailed: %s", watch.user_id, NOT_CONFIGURED_ERROR)
    else:
        dispatcher.submit(
            AlertEmailJob(
                alert_id=alert_id,
                user_id=watch.user_id,
                product_title=product.title,
                image_url=product.image_url,
                product_url=product.url,
                old_price=old_price,
                new_price=product.current_price,
                reason=reason,
                target_price=watch.target_price,
                detected_at=detected_at,
            )
        )

    return Alert.from_document({**alert.to_document(), "_id": alert_id})

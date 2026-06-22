import smtplib
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import mongomock
import pytest

from app.models import Alert, PriceHistory, Product, Store, Watch, init_db
from app.services import alerts as alerts_module
from app.services import tracker
from app.services.alert_email import AlertEmailJob, render_alert_email
from app.services.alerts import (
    NOT_CONFIGURED_ERROR,
    AlertDispatcher,
    SmtpEmailSender,
    process_price_drop,
)

URL = "https://www.flipkart.com/sony/p/itm1"
T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
EMAILS = {"alice": "alice@example.com", "bob": "bob@example.com"}


class FakeSMTP:
    """Stands in for smtplib.SMTP; shared state lives on the class-level `log`."""

    def __init__(self, fail_times=0, error=None, gate=None):
        self.fail_times = fail_times
        self.error = error or smtplib.SMTPServerDisconnected("connection lost")
        self.gate = gate
        self.sent = []
        self.attempts = 0
        self.events = []

    def __call__(self, host, port, timeout=None):
        self.events.append(("connect", host, port))
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        self.events.append(("starttls",))

    def login(self, username, password):
        self.events.append(("login", username, password))

    def send_message(self, message):
        self.attempts += 1
        if self.gate is not None:
            self.gate.wait(timeout=5)
        if self.attempts <= self.fail_times:
            raise self.error
        self.sent.append(message)


@pytest.fixture
def db():
    database = mongomock.MongoClient(tz_aware=True).pricescope_test
    init_db(database)
    return database


@pytest.fixture
def smtp():
    return FakeSMTP()


def make_dispatcher(db, smtp, lookup=EMAILS.get, sleeps=None, **kwargs):
    sender = SmtpEmailSender(
        host="smtp.example.com",
        username="bot@example.com",
        password="app-password",
        smtp_factory=smtp,
    )
    return AlertDispatcher(
        db,
        sender,
        lookup,
        sleeper=(sleeps.append if sleeps is not None else (lambda s: None)),
        **kwargs,
    )


def add_product(db, price="1000"):
    product = Product(
        store="flipkart",
        url=URL,
        title="Sony Headphones",
        image_url="https://cdn.example.com/sony.jpg",
        current_price=price,
        last_checked_at=T0,
        created_at=T0,
    )
    product_id = db.products.insert_one(product.to_document()).inserted_id
    return Product.from_document({**product.to_document(), "_id": product_id})


def add_watch(db, product, user="alice", **kwargs):
    db.watches.insert_one(Watch(user_id=user, product_id=product._id, **kwargs).to_document())


def add_history(db, product, price, days_ago, now=T0):
    db.price_history.insert_one(
        PriceHistory(
            product_id=product._id,
            price=price,
            in_stock=True,
            scraped_at=now - timedelta(days=days_ago),
        ).to_document()
    )


def drop_to(db, product, new_price, dispatcher, detected_at=T0, old_price=None):
    """Simulate record_price noticing a drop and return the updated product."""
    old_price = old_price or product.current_price
    updated = Product.from_document(
        {**product.to_document(), "current_price": Decimal(new_price), "_id": product._id}
    )
    alerts = process_price_drop(
        db, updated, old_price, detected_at=detected_at, now=detected_at, dispatcher=dispatcher
    )
    dispatcher.join()
    return updated, alerts


def stored_alerts(db):
    return [Alert.from_document(d) for d in db.alerts.find({}).sort("detected_at", 1)]


def test_target_price_hit_sends_email_and_records_alert(db, smtp):
    product = add_product(db, "1000")
    add_watch(db, product, target_price="900")
    dispatcher = make_dispatcher(db, smtp)

    _, created = drop_to(db, product, "850", dispatcher, detected_at=T0)

    assert len(created) == 1
    [alert] = stored_alerts(db)
    assert alert.reason.value == "target_price"
    assert alert.email_status.value == "sent"
    assert alert.attempts == 1
    assert alert.error is None
    assert alert.old_price == Decimal("1000.00")
    assert alert.new_price == Decimal("850.00")
    assert alert.sent_at is not None
    assert alert.latency_ms is not None and alert.latency_ms >= 0

    [message] = smtp.sent
    assert message["To"] == "alice@example.com"
    assert message["From"] == "bot@example.com"
    body = message.get_body(("plain",)).get_content()
    assert "Sony Headphones" in body
    assert "₹1,000.00" in body and "₹850.00" in body
    assert "15.0% off" in body
    assert URL in body
    assert ("login", "bot@example.com", "app-password") in smtp.events
    assert ("starttls",) in smtp.events
    watch = db.watches.find_one({"user_id": "alice"})
    assert watch["last_alerted_at"] == T0


def test_price_above_target_sends_nothing(db, smtp):
    product = add_product(db, "1000")
    add_watch(db, product, target_price="700")
    dispatcher = make_dispatcher(db, smtp)

    _, created = drop_to(db, product, "850", dispatcher)

    assert created == []
    assert smtp.sent == []
    assert db.alerts.count_documents({}) == 0


def test_price_rise_never_alerts_even_below_target(db, smtp):
    product = add_product(db, "500")
    add_watch(db, product, target_price="900")
    dispatcher = make_dispatcher(db, smtp)

    updated = Product.from_document({**product.to_document(), "current_price": Decimal("600"), "_id": product._id})
    created = process_price_drop(db, updated, Decimal("500"), dispatcher=dispatcher)

    assert created == []


def test_30_day_low_triggers_alert(db, smtp):
    product = add_product(db, "1000")
    add_watch(db, product, alert_on_30d_low=True)
    add_history(db, product, "1200", 20)
    add_history(db, product, "1000", 1)
    add_history(db, product, "850", 0)  # the observation being alerted on
    dispatcher = make_dispatcher(db, smtp)

    _, created = drop_to(db, product, "850", dispatcher)

    assert len(created) == 1
    assert stored_alerts(db)[0].reason.value == "30d_low"
    html = smtp.sent[0].get_body(("html",)).get_content()
    assert "Lowest price in the last 30 days" in html


def test_no_30_day_low_alert_when_cheaper_price_exists(db, smtp):
    product = add_product(db, "1000")
    add_watch(db, product, alert_on_30d_low=True)
    add_history(db, product, "700", 10)
    add_history(db, product, "850", 0)
    dispatcher = make_dispatcher(db, smtp)

    _, created = drop_to(db, product, "850", dispatcher)

    assert created == []
    assert smtp.sent == []


def test_30_day_low_flag_off_means_no_alert(db, smtp):
    product = add_product(db, "1000")
    add_watch(db, product)
    add_history(db, product, "850", 0)
    dispatcher = make_dispatcher(db, smtp)

    _, created = drop_to(db, product, "850", dispatcher)

    assert created == []


def test_target_reason_wins_when_both_conditions_hold(db, smtp):
    product = add_product(db, "1000")
    add_watch(db, product, target_price="900", alert_on_30d_low=True)
    add_history(db, product, "850", 0)
    dispatcher = make_dispatcher(db, smtp)

    drop_to(db, product, "850", dispatcher)

    assert [a.reason.value for a in stored_alerts(db)] == ["target_price"]
    assert len(smtp.sent) == 1


def test_same_price_does_not_alert_twice(db, smtp):
    product = add_product(db, "1000")
    add_watch(db, product, target_price="900")
    dispatcher = make_dispatcher(db, smtp)

    drop_to(db, product, "850", dispatcher, detected_at=T0)
    # Price bounces up then drops back to 850, well after the 24h window.
    _, created = drop_to(
        db, product, "850", dispatcher, detected_at=T0 + timedelta(days=3), old_price=Decimal("950")
    )

    assert created == []
    assert len(smtp.sent) == 1


def test_only_one_alert_per_24h_unless_price_drops_further(db, smtp):
    product = add_product(db, "1000")
    add_watch(db, product, target_price="950")
    dispatcher = make_dispatcher(db, smtp)

    drop_to(db, product, "900", dispatcher, detected_at=T0)
    # Bounce to 960, drop to 920 an hour later: a drop, but not below 900.
    _, repeat = drop_to(
        db, product, "920", dispatcher, detected_at=T0 + timedelta(hours=1), old_price=Decimal("960")
    )
    # Dropping further than the last alert within 24h is allowed.
    _, further = drop_to(
        db, product, "880", dispatcher, detected_at=T0 + timedelta(hours=2), old_price=Decimal("920")
    )

    assert repeat == []
    assert len(further) == 1
    assert [a.new_price for a in stored_alerts(db)] == [Decimal("900.00"), Decimal("880.00")]
    assert len(smtp.sent) == 2


def test_alert_allowed_again_after_24_hours(db, smtp):
    product = add_product(db, "1000")
    add_watch(db, product, target_price="950")
    dispatcher = make_dispatcher(db, smtp)

    drop_to(db, product, "900", dispatcher, detected_at=T0)
    _, later = drop_to(
        db,
        product,
        "920",
        dispatcher,
        detected_at=T0 + timedelta(hours=25),
        old_price=Decimal("960"),
    )

    assert len(later) == 1


def test_failed_alert_does_not_suppress_the_next_one(db):
    product = add_product(db, "1000")
    add_watch(db, product, target_price="950")
    failing = make_dispatcher(db, FakeSMTP(fail_times=99))
    working_smtp = FakeSMTP()
    working = make_dispatcher(db, working_smtp)

    drop_to(db, product, "900", failing, detected_at=T0)
    _, created = drop_to(
        db, product, "900", working, detected_at=T0 + timedelta(minutes=30), old_price=Decimal("960")
    )

    assert len(created) == 1
    assert [a.email_status.value for a in stored_alerts(db)] == ["failed", "sent"]


def test_each_watcher_is_alerted_only_if_their_own_rules_match(db, smtp):
    product = add_product(db, "1000")
    add_watch(db, product, user="alice", target_price="900")
    add_watch(db, product, user="bob", target_price="500")
    dispatcher = make_dispatcher(db, smtp)

    drop_to(db, product, "850", dispatcher)

    assert [m["To"] for m in smtp.sent] == ["alice@example.com"]
    assert [a.user_id for a in stored_alerts(db)] == ["alice"]


def test_email_failure_is_retried_with_backoff_then_succeeds(db):
    smtp = FakeSMTP(fail_times=2)
    sleeps = []
    product = add_product(db, "1000")
    add_watch(db, product, target_price="900")
    dispatcher = make_dispatcher(db, smtp, sleeps=sleeps, backoff_seconds=2.0)

    drop_to(db, product, "850", dispatcher)

    [alert] = stored_alerts(db)
    assert smtp.attempts == 3
    assert alert.attempts == 3
    assert alert.email_status.value == "sent"
    assert alert.error is None
    assert sleeps == [2.0, 4.0]
    assert len(smtp.sent) == 1


def test_email_failure_after_max_attempts_is_recorded(db):
    smtp = FakeSMTP(fail_times=99)
    sleeps = []
    product = add_product(db, "1000")
    add_watch(db, product, target_price="900")
    dispatcher = make_dispatcher(db, smtp, sleeps=sleeps)

    _, created = drop_to(db, product, "850", dispatcher)

    [alert] = stored_alerts(db)
    assert len(created) == 1
    assert smtp.attempts == 3
    assert alert.attempts == 3
    assert alert.email_status.value == "failed"
    assert alert.sent_at is None
    assert alert.latency_ms is None
    assert "SMTPServerDisconnected" in alert.error
    assert len(sleeps) == 2
    assert smtp.sent == []


def test_user_without_email_fails_without_retrying(db, smtp):
    product = add_product(db, "1000")
    add_watch(db, product, user="ghost", target_price="900")
    sleeps = []
    dispatcher = make_dispatcher(db, smtp, lookup=lambda uid: None, sleeps=sleeps)

    drop_to(db, product, "850", dispatcher)

    [alert] = stored_alerts(db)
    assert alert.email_status.value == "failed"
    assert alert.attempts == 1
    assert "no email" in alert.error
    assert sleeps == []
    assert smtp.attempts == 0


def test_lookup_errors_are_retried(db, smtp):
    calls = []

    def flaky_lookup(uid):
        calls.append(uid)
        if len(calls) == 1:
            raise RuntimeError("firebase unavailable")
        return "alice@example.com"

    product = add_product(db, "1000")
    add_watch(db, product, target_price="900")
    dispatcher = make_dispatcher(db, smtp, lookup=flaky_lookup)

    drop_to(db, product, "850", dispatcher)

    assert stored_alerts(db)[0].email_status.value == "sent"
    assert len(calls) == 2


def test_alert_is_recorded_as_failed_when_email_is_not_configured(db):
    product = add_product(db, "1000")
    add_watch(db, product, target_price="900")
    updated = Product.from_document({**product.to_document(), "current_price": Decimal("850"), "_id": product._id})

    created = process_price_drop(db, updated, Decimal("1000"), dispatcher=None)

    [alert] = stored_alerts(db)
    assert len(created) == 1
    assert alert.email_status.value == "failed"
    assert alert.error == NOT_CONFIGURED_ERROR


def test_latency_is_detected_at_to_sent_at(db, smtp):
    product = add_product(db, "1000")
    add_watch(db, product, target_price="900")
    sent_clock = T0 + timedelta(milliseconds=1250)
    dispatcher = make_dispatcher(db, smtp, clock=lambda: sent_clock)

    drop_to(db, product, "850", dispatcher, detected_at=T0)

    [alert] = stored_alerts(db)
    assert alert.sent_at == sent_clock
    assert alert.latency_ms == 1250.0


def test_record_price_alerts_on_drop_without_blocking_on_smtp(db):
    gate = threading.Event()
    smtp = FakeSMTP(gate=gate)
    dispatcher = make_dispatcher(db, smtp)
    scraper = StubScraper("1000")
    product = tracker.add_product(URL, db=db, scraper=scraper, now=T0)
    add_watch(db, product, target_price="900")

    scraper.price = Decimal("850")
    updated = tracker.record_price(
        product, db=db, scraper=scraper, now=T0 + timedelta(hours=6), alert_dispatcher=dispatcher
    )

    # record_price returned while the SMTP server is still "busy".
    assert updated.current_price == Decimal("850.00")
    assert smtp.sent == []
    assert stored_alerts(db)[0].email_status.value == "pending"

    gate.set()
    dispatcher.join()
    assert stored_alerts(db)[0].email_status.value == "sent"
    assert len(smtp.sent) == 1


def test_record_price_does_not_alert_without_a_drop(db, smtp):
    dispatcher = make_dispatcher(db, smtp)
    scraper = StubScraper("1000")
    product = tracker.add_product(URL, db=db, scraper=scraper, now=T0)
    add_watch(db, product, target_price="2000")

    tracker.record_price(product, db=db, scraper=scraper, now=T0 + timedelta(hours=6), alert_dispatcher=dispatcher)
    scraper.price = Decimal("1100")
    tracker.record_price(product, db=db, scraper=scraper, now=T0 + timedelta(hours=12), alert_dispatcher=dispatcher)
    dispatcher.join()

    assert db.alerts.count_documents({}) == 0


def test_alert_engine_errors_never_break_record_price(db, monkeypatch):
    scraper = StubScraper("1000")
    product = tracker.add_product(URL, db=db, scraper=scraper, now=T0)
    add_watch(db, product, target_price="900")

    def boom(*args, **kwargs):
        raise RuntimeError("alert bug")

    monkeypatch.setattr(alerts_module, "process_price_drop", boom)
    scraper.price = Decimal("850")

    updated = tracker.record_price(product, db=db, scraper=scraper, now=T0 + timedelta(hours=6))

    assert updated.current_price == Decimal("850.00")
    stored = Product.from_document(db.products.find_one({"_id": product._id}))
    assert stored.current_price == Decimal("850.00")


def test_dispatcher_shutdown_drains_queue(db, smtp):
    product = add_product(db, "1000")
    add_watch(db, product, target_price="900")
    dispatcher = make_dispatcher(db, smtp)
    updated = Product.from_document({**product.to_document(), "current_price": Decimal("850"), "_id": product._id})

    process_price_drop(db, updated, Decimal("1000"), detected_at=T0, dispatcher=dispatcher)
    dispatcher.shutdown()

    assert len(smtp.sent) == 1


def test_email_template_escapes_html_and_includes_all_details():
    job = AlertEmailJob(
        alert_id=None,
        user_id="alice",
        product_title="<script>alert(1)</script> Headphones",
        image_url="https://cdn.example.com/a.jpg?x=1&y=2",
        product_url="https://www.flipkart.com/p?id=1&ref=a",
        old_price=Decimal("2000.00"),
        new_price=Decimal("1500.00"),
        reason=alerts_module.AlertReason.TARGET_PRICE,
        target_price=Decimal("1600.00"),
        detected_at=T0,
    )

    subject, text, html = render_alert_email(job)

    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "₹2,000.00" in html and "₹1,500.00" in html
    assert "-25.0%" in html
    assert "Target price reached (your target: ₹1,600.00)" in html
    assert 'src="https://cdn.example.com/a.jpg?x=1&amp;y=2"' in html
    assert 'href="https://www.flipkart.com/p?id=1&amp;ref=a"' in html
    assert "(-25.0%)" in subject
    assert "https://www.flipkart.com/p?id=1&ref=a" in text


@pytest.mark.parametrize(
    ("security", "expects_starttls"), [("starttls", True), ("none", False)]
)
def test_smtp_sender_security_modes(security, expects_starttls):
    smtp = FakeSMTP()
    sender = SmtpEmailSender("smtp.example.com", 2525, "u", "p", security=security, smtp_factory=smtp)

    sender.send("a@example.com", "Subject", "text", "<p>html</p>")

    assert (("starttls",) in smtp.events) is expects_starttls
    assert smtp.events[0] == ("connect", "smtp.example.com", 2525)
    assert smtp.sent[0]["From"] == "u"


def test_smtp_sender_rejects_unknown_security():
    with pytest.raises(ValueError, match="SMTP_SECURITY"):
        SmtpEmailSender("smtp.example.com", security="plain")


class StubScraper:
    store = Store.FLIPKART

    def __init__(self, price):
        self.price = Decimal(price)

    def fetch(self, url):
        return "<html></html>"

    def parse(self, html):
        return {
            "title": "Sony Headphones",
            "price": self.price,
            "image_url": "https://cdn.example.com/sony.jpg",
            "in_stock": True,
        }

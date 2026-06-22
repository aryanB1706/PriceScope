"""Simulate price drops and report alert latency (detected_at -> sent_at).

By default the SMTP server is an in-process fake, so the numbers measure
PriceScope's own pipeline (queueing, rendering, retries) plus an optional
simulated network delay. Use --real to send through the SMTP server from .env.

    python scripts/measure_alert_latency.py
    python scripts/measure_alert_latency.py --drops 20 --smtp-delay-ms 150
    python scripts/measure_alert_latency.py --real --to you@example.com --drops 3
"""

import argparse
import math
import statistics
import sys
import time
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mongomock  # noqa: E402

from app.config import Config  # noqa: E402
from app.models import Product, Store, Watch, init_db  # noqa: E402
from app.services.alerts import AlertDispatcher, SmtpEmailSender  # noqa: E402
from app.services.tracker import add_product, record_price  # noqa: E402

URL = "https://www.flipkart.com/latency-test/p/itm0"
USER_ID = "latency-user"


class FakeSMTP:
    def __init__(self, delay_seconds: float):
        self.delay = delay_seconds

    def __call__(self, host, port, timeout=None):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        pass

    def login(self, username, password):
        pass

    def send_message(self, message):
        time.sleep(self.delay)


class SimulatedScraper:
    store = Store.FLIPKART

    def __init__(self, price: Decimal):
        self.price = price

    def fetch(self, url):
        return "<html></html>"

    def parse(self, html):
        return {
            "title": "Latency Test Headphones",
            "price": self.price,
            "image_url": "https://cdn.example.com/test.jpg",
            "in_stock": True,
        }


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile."""
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def build_dispatcher(args, db) -> AlertDispatcher:
    if args.real:
        if not Config.SMTP_HOST:
            sys.exit("--real needs SMTP_HOST (and credentials) set in backend/.env")
        sender = SmtpEmailSender(
            host=Config.SMTP_HOST,
            port=Config.SMTP_PORT,
            username=Config.SMTP_USERNAME,
            password=Config.SMTP_PASSWORD,
            from_addr=Config.SMTP_FROM,
            security=Config.SMTP_SECURITY,
        )
    else:
        sender = SmtpEmailSender(
            host="fake.smtp",
            from_addr="alerts@example.com",
            security="none",
            smtp_factory=FakeSMTP(args.smtp_delay_ms / 1000),
        )
    recipient = args.to if args.real else "user@example.com"
    return AlertDispatcher(db, sender, lambda uid: recipient)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--drops", type=int, default=20)
    parser.add_argument("--smtp-delay-ms", type=float, default=0.0)
    parser.add_argument("--real", action="store_true", help="send real emails")
    parser.add_argument("--to", help="recipient for --real")
    args = parser.parse_args()

    if args.drops < 1:
        sys.exit("--drops must be at least 1")
    if args.real and not args.to:
        sys.exit("--real needs --to <address>")

    db = mongomock.MongoClient(tz_aware=True).latency_test
    init_db(db)
    dispatcher = build_dispatcher(args, db)

    start_price = Decimal("10000")
    scraper = SimulatedScraper(start_price)
    product = add_product(URL, db=db, scraper=scraper)
    db.watches.insert_one(
        Watch(user_id=USER_ID, product_id=product._id, target_price=start_price).to_document()
    )

    # Each drop is lower than the last alert, so the anti-spam rules let it through.
    for step in range(1, args.drops + 1):
        scraper.price = start_price - Decimal(step * 100)
        product = record_price(product, db=db, scraper=scraper, alert_dispatcher=dispatcher)
        dispatcher.join()

    rows = list(db.alerts.find({}))
    latencies = [row["latency_ms"] for row in rows if row["email_status"] == "sent"]
    failed = len(rows) - len(latencies)

    print(f"Simulated {args.drops} price drops -> {len(rows)} alerts, {failed} failed")
    if not latencies:
        sys.exit("No alert was delivered, so there is no latency to report.")

    print(f"Latency (detected_at -> handed to SMTP), n={len(latencies)}:")
    print(f"  min  {min(latencies):9.1f} ms")
    print(f"  avg  {statistics.fmean(latencies):9.1f} ms")
    print(f"  p95  {percentile(latencies, 95):9.1f} ms")
    print(f"  max  {max(latencies):9.1f} ms")
    mode = "real SMTP" if args.real else f"fake SMTP (+{args.smtp_delay_ms:g} ms simulated)"
    print(f"Mode: {mode}")


if __name__ == "__main__":
    main()

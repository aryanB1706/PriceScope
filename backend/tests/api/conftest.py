from datetime import datetime, timedelta, timezone
from decimal import Decimal

import mongomock
import pytest
from firebase_admin import auth

from app import create_app
from app.models import Alert, PriceHistory, Product, Store, Watch, init_db

FRONTEND_ORIGIN = "http://localhost:5173"
FLIPKART_URL = "https://www.flipkart.com/sony-headphones/p/itm111"
MYNTRA_URL = "https://www.myntra.com/tshirts/celio/red-tshirt/123/buy"

TOKENS = {"token-alice": "alice", "token-bob": "bob"}


class FakeScraper:
    def __init__(self, url, price="1000", error=None):
        self.url = url
        self.price = Decimal(price)
        self.error = error
        self.store = Store.MYNTRA if "myntra" in url else Store.FLIPKART

    def fetch(self, url):
        if self.error:
            raise self.error
        return "<html></html>"

    def parse(self, html):
        return {
            "title": "Sony Headphones",
            "price": self.price,
            "image_url": "https://cdn.example.com/i.jpg",
            "in_stock": True,
        }


class ScraperControl:
    """Lets a test choose the price or failure the fake scraper returns."""

    def __init__(self):
        self.price = "1000"
        self.error = None
        self.created = 0

    def __call__(self, url, **options):
        self.created += 1
        return FakeScraper(url, self.price, self.error)


@pytest.fixture
def db():
    database = mongomock.MongoClient(tz_aware=True).pricescope_test
    init_db(database)
    return database


@pytest.fixture
def scraper(monkeypatch):
    control = ScraperControl()
    monkeypatch.setattr("app.services.tracker.get_scraper", control)
    return control


@pytest.fixture
def api_app(db, monkeypatch):
    def fake_verify(token):
        if token in TOKENS:
            return {"uid": TOKENS[token]}
        raise auth.InvalidIdTokenError("bad token")

    monkeypatch.setattr("app.services.auth.verify_firebase_token", fake_verify)

    app = create_app({"TESTING": True, "FRONTEND_ORIGIN": FRONTEND_ORIGIN})
    app.extensions["mongo_db"] = db
    return app


@pytest.fixture
def api(api_app):
    return api_app.test_client()


@pytest.fixture
def alice():
    return {"Authorization": "Bearer token-alice"}


@pytest.fixture
def bob():
    return {"Authorization": "Bearer token-bob"}


@pytest.fixture
def make_product(db):
    def _make(url=FLIPKART_URL, price="1000", title="Sony Headphones"):
        now = datetime.now(timezone.utc)
        product = Product(
            store="flipkart",
            url=url,
            title=title,
            image_url="https://cdn.example.com/i.jpg",
            current_price=price,
            last_checked_at=now,
            created_at=now,
        )
        return db.products.insert_one(product.to_document()).inserted_id

    return _make


@pytest.fixture
def make_watch(db):
    def _make(user_id, product_id, **kwargs):
        watch = Watch(user_id=user_id, product_id=product_id, **kwargs)
        return db.watches.insert_one(watch.to_document()).inserted_id

    return _make


@pytest.fixture
def add_history(db):
    def _add(product_id, price, days_ago, in_stock=True):
        db.price_history.insert_one(
            PriceHistory(
                product_id=product_id,
                price=price,
                in_stock=in_stock,
                scraped_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
            ).to_document()
        )

    return _add


@pytest.fixture
def add_alert(db):
    def _add(user_id, product_id, new_price, minutes_ago):
        db.alerts.insert_one(
            Alert(
                user_id=user_id,
                product_id=product_id,
                reason="target_price",
                old_price="1000",
                new_price=new_price,
                detected_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
            ).to_document()
        )

    return _add

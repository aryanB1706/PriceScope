from datetime import datetime, timezone
from decimal import Decimal

import pytest
from bson import ObjectId
from bson.decimal128 import Decimal128

from app.models import Alert, AlertReason, EmailStatus, PriceHistory, Product, Store, Watch

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


def test_product_validates_and_serializes_to_document():
    product = Product(
        store="flipkart",
        url="https://www.flipkart.com/item",
        title="Wireless Headphones",
        image_url="https://cdn.example.com/headphones.jpg",
        current_price="2999.999",
        created_at=NOW,
        last_checked_at=NOW,
    )

    assert product.store is Store.FLIPKART
    assert product.current_price == Decimal("3000.00")

    document = product.to_document()

    assert document["store"] == "flipkart"
    assert document["current_price"] == Decimal128("3000.00")
    assert document["created_at"] == NOW
    assert "_id" not in document


def test_product_round_trips_from_document():
    product_id = ObjectId()
    document = {
        "_id": product_id,
        "store": "croma",
        "url": "https://www.croma.com/item",
        "title": "Smart Speaker",
        "image_url": "https://cdn.example.com/speaker.jpg",
        "current_price": Decimal128("4999.00"),
        "currency": "INR",
        "last_checked_at": NOW,
        "created_at": NOW,
        "consecutive_failures": 2,
    }

    product = Product.from_document(document)

    assert product._id == product_id
    assert product.current_price == Decimal("4999.00")
    assert product.to_document() == document


def test_price_history_serializes_observation():
    product_id = ObjectId()

    observation = PriceHistory(
        product_id=str(product_id),
        price="149.50",
        in_stock=False,
        scraped_at=NOW,
    )

    assert observation.product_id == product_id
    assert observation.to_document() == {
        "product_id": product_id,
        "price": Decimal128("149.50"),
        "in_stock": False,
        "scraped_at": NOW,
    }


def test_watch_supports_optional_target_and_alert_state():
    product_id = ObjectId()

    watch = Watch(
        user_id="firebase-uid",
        product_id=product_id,
        target_price="999.99",
        alert_on_30d_low=True,
        created_at=NOW,
        last_alerted_at=NOW,
    )

    document = watch.to_document()

    assert document["target_price"] == Decimal128("999.99")
    assert document["alert_on_30d_low"] is True
    assert Watch.from_document(document) == watch


def test_watch_allows_no_target_price():
    watch = Watch(user_id="firebase-uid", product_id=ObjectId(), created_at=NOW)

    assert watch.target_price is None
    assert watch.alert_on_30d_low is False
    assert watch.last_alerted_at is None


def test_alert_serializes_reason_and_email_status():
    alert = Alert(
        user_id="firebase-uid",
        product_id=ObjectId(),
        reason="30d_low",
        old_price="2499.00",
        new_price="1999.00",
        detected_at=NOW,
        sent_at=NOW,
        email_status="sent",
        attempts=2,
        error="SMTPServerDisconnected: retry",
        latency_ms=842.5,
    )

    document = alert.to_document()

    assert alert.reason is AlertReason.THIRTY_DAY_LOW
    assert alert.email_status is EmailStatus.SENT
    assert document["reason"] == "30d_low"
    assert document["email_status"] == "sent"
    assert document["old_price"] == Decimal128("2499.00")
    assert document["attempts"] == 2
    assert document["latency_ms"] == 842.5
    assert Alert.from_document(document) == alert


def test_alert_starts_pending_and_unsent():
    alert = Alert(
        user_id="firebase-uid",
        product_id=ObjectId(),
        reason="target_price",
        old_price="100",
        new_price="90",
    )

    assert alert.email_status is EmailStatus.PENDING
    assert alert.sent_at is None
    assert alert.attempts == 0
    assert alert.error is None
    assert alert.latency_ms is None


@pytest.mark.parametrize(
    "factory",
    [
        lambda: Product(
            store="amazon",
            url="https://www.flipkart.com/item",
            title="Item",
            image_url="https://cdn.example.com/item.jpg",
            current_price="10.00",
        ),
        lambda: PriceHistory(
            product_id=str(ObjectId()),
            price="10.00",
            in_stock="yes",
        ),
        lambda: Watch(user_id="", product_id=ObjectId()),
        lambda: Alert(
            user_id="firebase-uid",
            product_id=ObjectId(),
            reason="price_drop",
            old_price="10.00",
            new_price="9.00",
        ),
    ],
)
def test_documents_reject_invalid_data(factory):
    with pytest.raises(ValueError):
        factory()

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from bson import ObjectId
from bson.decimal128 import Decimal128

from app.models import (
    AlertReason,
    EmailStatus,
    Store,
    validate_alert_reason,
    validate_bool,
    validate_currency,
    validate_datetime,
    validate_email_status,
    validate_firebase_uid,
    validate_object_id,
    validate_price,
    validate_store,
    validate_url,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("flipkart", Store.FLIPKART),
        ("myntra", Store.MYNTRA),
        (Store.CROMA, Store.CROMA),
    ],
)
def test_validate_store_accepts_supported_stores(raw, expected):
    assert validate_store(raw) == expected


@pytest.mark.parametrize("raw", ["amazon", "", None])
def test_validate_store_rejects_unsupported_stores(raw):
    with pytest.raises(ValueError, match="store must be one of"):
        validate_store(raw)


def test_validate_alert_reason_and_email_status():
    assert validate_alert_reason("target_price") == AlertReason.TARGET_PRICE
    assert validate_email_status("sent") == EmailStatus.SENT

    with pytest.raises(ValueError, match="reason must be one of"):
        validate_alert_reason("price_drop")
    with pytest.raises(ValueError, match="email_status must be one of"):
        validate_email_status("delivered")


@pytest.mark.parametrize(
    "url",
    ["https://www.flipkart.com/product/p/itm123", "http://croma.com/item"],
)
def test_validate_url_accepts_absolute_http_urls(url):
    assert validate_url(url) == url


@pytest.mark.parametrize(
    "url",
    ["flipkart.com/item", "ftp://croma.com/item", "https://", ""],
)
def test_validate_url_rejects_invalid_urls(url):
    with pytest.raises(ValueError, match="url"):
        validate_url(url)


def test_validate_url_trims_whitespace():
    assert validate_url("  https://croma.com/item  ") == "https://croma.com/item"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1299", Decimal("1299.00")),
        (10.555, Decimal("10.56")),
        (Decimal("99.9"), Decimal("99.90")),
        (Decimal128("49.99"), Decimal("49.99")),
    ],
)
def test_validate_price_normalizes_to_two_decimal_places(raw, expected):
    assert validate_price(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [0, -1, "NaN", "Infinity", "not-a-number", True, None],
)
def test_validate_price_rejects_invalid_values(raw):
    with pytest.raises(ValueError, match="price"):
        validate_price(raw)


def test_validate_currency_normalizes_case():
    assert validate_currency("inr") == "INR"
    assert validate_currency(" usd ") == "USD"

    with pytest.raises(ValueError, match="currency"):
        validate_currency("rupees")


def test_validate_datetime_requires_timezone_and_converts_to_utc():
    ist = timezone(timedelta(hours=5, minutes=30))
    value = datetime(2026, 1, 1, 12, 0, tzinfo=ist)

    assert validate_datetime(value, "created_at") == datetime(
        2026, 1, 1, 6, 30, tzinfo=timezone.utc
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        validate_datetime(datetime(2026, 1, 1), "created_at")


def test_validate_object_id_accepts_object_ids_and_hex_strings():
    object_id = ObjectId()

    assert validate_object_id(object_id) == object_id
    assert validate_object_id(str(object_id)) == object_id

    with pytest.raises(ValueError, match="product_id"):
        validate_object_id("not-an-object-id")


def test_validate_firebase_uid_rejects_blank_values_and_trims():
    assert validate_firebase_uid("  firebase-uid  ") == "firebase-uid"

    with pytest.raises(ValueError, match="user_id"):
        validate_firebase_uid("   ")


def test_validate_bool_rejects_truthy_non_booleans():
    assert validate_bool(True, "in_stock") is True
    assert validate_bool(False, "in_stock") is False

    with pytest.raises(ValueError, match="boolean"):
        validate_bool(1, "in_stock")

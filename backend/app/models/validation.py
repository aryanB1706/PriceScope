from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import urlparse

from bson import ObjectId
from bson.decimal128 import Decimal128
from bson.errors import InvalidId

from app.models.enums import AlertReason, EmailStatus, Store

PRICE_QUANTUM = Decimal("0.01")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_enum(value, enum_type, field_name: str):
    try:
        return enum_type(value)
    except (TypeError, ValueError):
        allowed = ", ".join(member.value for member in enum_type)
        raise ValueError(f"{field_name} must be one of: {allowed}") from None


def validate_store(value) -> Store:
    return _coerce_enum(value, Store, "store")


def validate_alert_reason(value) -> AlertReason:
    return _coerce_enum(value, AlertReason, "reason")


def validate_email_status(value) -> EmailStatus:
    return _coerce_enum(value, EmailStatus, "email_status")


def validate_non_empty_string(value, field_name: str, max_length: int = 2048) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")

    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field_name} must be at most {max_length} characters")

    return normalized


def validate_url(value, field_name: str = "url") -> str:
    normalized = validate_non_empty_string(value, field_name)
    parsed = urlparse(normalized)

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field_name} must be an absolute HTTP(S) URL")

    return normalized


def validate_firebase_uid(value) -> str:
    return validate_non_empty_string(value, "user_id", max_length=128)


def validate_object_id(value, field_name: str = "product_id") -> ObjectId:
    if isinstance(value, ObjectId):
        return value

    if isinstance(value, str):
        try:
            return ObjectId(value)
        except (InvalidId, TypeError):
            pass

    raise ValueError(f"{field_name} must be a valid ObjectId")


def validate_price(value, field_name: str = "price") -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field_name} must be a positive number")

    if isinstance(value, Decimal128):
        value = value.to_decimal()

    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field_name} must be a positive number") from None

    if not amount.is_finite():
        raise ValueError(f"{field_name} must be a finite number")
    if amount <= 0:
        raise ValueError(f"{field_name} must be greater than zero")

    return amount.quantize(PRICE_QUANTUM, rounding=ROUND_HALF_UP)


def validate_optional_price(value, field_name: str = "target_price") -> Decimal | None:
    if value is None:
        return None
    return validate_price(value, field_name)


def validate_currency(value) -> str:
    if not isinstance(value, str):
        raise ValueError("currency must be a string")

    normalized = value.strip().upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise ValueError("currency must be a three-letter ISO code")

    return normalized


def validate_datetime(value, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")

    return value.astimezone(timezone.utc)


def validate_optional_datetime(
    value, field_name: str
) -> datetime | None:
    if value is None:
        return None
    return validate_datetime(value, field_name)


def validate_non_negative_int(value, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    if value < 0:
        raise ValueError(f"{field_name} must not be negative")
    return value


def validate_bool(value, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def to_decimal128(value: Decimal) -> Decimal128:
    return Decimal128(value)

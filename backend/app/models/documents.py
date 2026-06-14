from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from bson import ObjectId

from app.models.enums import AlertReason, EmailStatus, Store
from app.models.validation import (
    to_decimal128,
    utc_now,
    validate_alert_reason,
    validate_bool,
    validate_currency,
    validate_datetime,
    validate_email_status,
    validate_firebase_uid,
    validate_non_empty_string,
    validate_non_negative_int,
    validate_object_id,
    validate_optional_datetime,
    validate_optional_price,
    validate_price,
    validate_store,
    validate_url,
)


@dataclass(frozen=True, slots=True)
class Product:
    store: Store
    url: str
    title: str
    image_url: str
    current_price: Decimal
    currency: str = "INR"
    last_checked_at: datetime = field(default_factory=utc_now)
    created_at: datetime = field(default_factory=utc_now)
    consecutive_failures: int = 0
    _id: ObjectId | None = None

    def __post_init__(self):
        object.__setattr__(self, "store", validate_store(self.store))
        object.__setattr__(self, "url", validate_url(self.url))
        object.__setattr__(
            self, "title", validate_non_empty_string(self.title, "title", 500)
        )
        object.__setattr__(self, "image_url", validate_url(self.image_url, "image_url"))
        object.__setattr__(
            self, "current_price", validate_price(self.current_price, "current_price")
        )
        object.__setattr__(self, "currency", validate_currency(self.currency))
        object.__setattr__(
            self,
            "last_checked_at",
            validate_datetime(self.last_checked_at, "last_checked_at"),
        )
        object.__setattr__(
            self, "created_at", validate_datetime(self.created_at, "created_at")
        )
        object.__setattr__(
            self,
            "consecutive_failures",
            validate_non_negative_int(
                self.consecutive_failures, "consecutive_failures"
            ),
        )

    def to_document(self) -> dict:
        document = {
            "store": self.store.value,
            "url": self.url,
            "title": self.title,
            "image_url": self.image_url,
            "current_price": to_decimal128(self.current_price),
            "currency": self.currency,
            "last_checked_at": self.last_checked_at,
            "created_at": self.created_at,
            "consecutive_failures": self.consecutive_failures,
        }
        if self._id is not None:
            document["_id"] = self._id
        return document

    @classmethod
    def from_document(cls, document: dict) -> "Product":
        return cls(
            _id=document.get("_id"),
            store=document["store"],
            url=document["url"],
            title=document["title"],
            image_url=document["image_url"],
            current_price=document["current_price"],
            currency=document["currency"],
            last_checked_at=document["last_checked_at"],
            created_at=document["created_at"],
            consecutive_failures=document.get("consecutive_failures", 0),
        )


@dataclass(frozen=True, slots=True)
class PriceHistory:
    product_id: ObjectId
    price: Decimal
    in_stock: bool
    scraped_at: datetime = field(default_factory=utc_now)
    _id: ObjectId | None = None

    def __post_init__(self):
        object.__setattr__(
            self, "product_id", validate_object_id(self.product_id, "product_id")
        )
        object.__setattr__(self, "price", validate_price(self.price, "price"))
        object.__setattr__(self, "in_stock", validate_bool(self.in_stock, "in_stock"))
        object.__setattr__(
            self, "scraped_at", validate_datetime(self.scraped_at, "scraped_at")
        )

    def to_document(self) -> dict:
        document = {
            "product_id": self.product_id,
            "price": to_decimal128(self.price),
            "in_stock": self.in_stock,
            "scraped_at": self.scraped_at,
        }
        if self._id is not None:
            document["_id"] = self._id
        return document

    @classmethod
    def from_document(cls, document: dict) -> "PriceHistory":
        return cls(
            _id=document.get("_id"),
            product_id=document["product_id"],
            price=document["price"],
            in_stock=document["in_stock"],
            scraped_at=document["scraped_at"],
        )


@dataclass(frozen=True, slots=True)
class Watch:
    user_id: str
    product_id: ObjectId
    target_price: Decimal | None = None
    alert_on_30d_low: bool = False
    created_at: datetime = field(default_factory=utc_now)
    last_alerted_at: datetime | None = None
    _id: ObjectId | None = None

    def __post_init__(self):
        object.__setattr__(self, "user_id", validate_firebase_uid(self.user_id))
        object.__setattr__(
            self, "product_id", validate_object_id(self.product_id, "product_id")
        )
        object.__setattr__(
            self,
            "target_price",
            validate_optional_price(self.target_price, "target_price"),
        )
        object.__setattr__(
            self,
            "alert_on_30d_low",
            validate_bool(self.alert_on_30d_low, "alert_on_30d_low"),
        )
        object.__setattr__(
            self, "created_at", validate_datetime(self.created_at, "created_at")
        )
        object.__setattr__(
            self,
            "last_alerted_at",
            validate_optional_datetime(self.last_alerted_at, "last_alerted_at"),
        )

    def to_document(self) -> dict:
        document = {
            "user_id": self.user_id,
            "product_id": self.product_id,
            "target_price": (
                to_decimal128(self.target_price)
                if self.target_price is not None
                else None
            ),
            "alert_on_30d_low": self.alert_on_30d_low,
            "created_at": self.created_at,
            "last_alerted_at": self.last_alerted_at,
        }
        if self._id is not None:
            document["_id"] = self._id
        return document

    @classmethod
    def from_document(cls, document: dict) -> "Watch":
        return cls(
            _id=document.get("_id"),
            user_id=document["user_id"],
            product_id=document["product_id"],
            target_price=document.get("target_price"),
            alert_on_30d_low=document["alert_on_30d_low"],
            created_at=document["created_at"],
            last_alerted_at=document.get("last_alerted_at"),
        )


@dataclass(frozen=True, slots=True)
class Alert:
    user_id: str
    product_id: ObjectId
    reason: AlertReason
    old_price: Decimal
    new_price: Decimal
    sent_at: datetime = field(default_factory=utc_now)
    email_status: EmailStatus = EmailStatus.PENDING
    _id: ObjectId | None = None

    def __post_init__(self):
        object.__setattr__(self, "user_id", validate_firebase_uid(self.user_id))
        object.__setattr__(
            self, "product_id", validate_object_id(self.product_id, "product_id")
        )
        object.__setattr__(self, "reason", validate_alert_reason(self.reason))
        object.__setattr__(self, "old_price", validate_price(self.old_price, "old_price"))
        object.__setattr__(self, "new_price", validate_price(self.new_price, "new_price"))
        object.__setattr__(
            self, "sent_at", validate_datetime(self.sent_at, "sent_at")
        )
        object.__setattr__(
            self, "email_status", validate_email_status(self.email_status)
        )

    def to_document(self) -> dict:
        document = {
            "user_id": self.user_id,
            "product_id": self.product_id,
            "reason": self.reason.value,
            "old_price": to_decimal128(self.old_price),
            "new_price": to_decimal128(self.new_price),
            "sent_at": self.sent_at,
            "email_status": self.email_status.value,
        }
        if self._id is not None:
            document["_id"] = self._id
        return document

    @classmethod
    def from_document(cls, document: dict) -> "Alert":
        return cls(
            _id=document.get("_id"),
            user_id=document["user_id"],
            product_id=document["product_id"],
            reason=document["reason"],
            old_price=document["old_price"],
            new_price=document["new_price"],
            sent_at=document["sent_at"],
            email_status=document["email_status"],
        )

from enum import StrEnum


class Store(StrEnum):
    FLIPKART = "flipkart"
    MYNTRA = "myntra"
    CROMA = "croma"


class AlertReason(StrEnum):
    TARGET_PRICE = "target_price"
    THIRTY_DAY_LOW = "30d_low"


class EmailStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"

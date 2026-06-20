from flask import request

from app.errors import ApiError, validation
from app.models import validate_bool, validate_optional_price, validate_url
from app.scrapers import ScraperError, scraper_class_for


def json_body() -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ApiError(400, "invalid_request", "Request body must be a JSON object")
    return body


def reject_unknown_fields(body: dict, allowed: set[str]) -> None:
    unknown = sorted(set(body) - allowed)
    if unknown:
        raise ApiError(
            400, "invalid_request", f"Unknown field(s): {', '.join(unknown)}"
        )


def parse_store_url(value) -> str:
    with validation():
        url = validate_url(value)

    try:
        scraper_class_for(url)
    except ScraperError:
        raise ApiError(
            400, "unsupported_store", "URL is not from a supported store"
        ) from None
    return url


def parse_target_price(value):
    with validation():
        return validate_optional_price(value, "target_price")


def parse_alert_flag(value) -> bool:
    with validation():
        return validate_bool(value, "alert_on_30d_low")


def int_query_param(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = request.args.get(name)
    if raw is None:
        return default

    try:
        value = int(raw)
    except ValueError:
        value = None
    if value is None or not minimum <= value <= maximum:
        raise ApiError(
            400, "invalid_request", f"{name} must be an integer from {minimum} to {maximum}"
        )
    return value

import json
import random
import time
from abc import ABC, abstractmethod
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import TypedDict
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from app.models import Store

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
}
BLOCKED_PAGE_MARKERS = (
    "verify you are human",
    "unusual traffic from your computer network",
    "please complete the security check",
    "enable javascript and cookies to continue",
    "access denied",
)
OUT_OF_STOCK_MARKERS = (
    "out of stock",
    "sold out",
    "currently unavailable",
    "temporarily unavailable",
    "notify me",
)
IN_STOCK_MARKERS = ("add to cart", "buy now")


class ScraperError(Exception):
    pass


class ScraperBlockedError(ScraperError):
    pass


class ScrapedProduct(TypedDict):
    title: str
    price: Decimal
    image_url: str
    in_stock: bool


class StructuredProduct(TypedDict):
    title: str
    price: Decimal
    image_url: str
    in_stock: bool | None


class BaseScraper(ABC):
    store: Store

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout: float = 15.0,
        max_retries: int = 3,
        backoff_factor: float = 1.0,
        delay_range: tuple[float, float] = (1.0, 3.0),
        respect_robots: bool = True,
        user_agent: str = DEFAULT_USER_AGENT,
        sleeper=time.sleep,
        randomizer=random.uniform,
    ):
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.delay_range = delay_range
        self.respect_robots = respect_robots
        self.user_agent = user_agent
        self._sleep = sleeper
        self._random = randomizer
        self._last_request_at: float | None = None
        self._robots_cache: dict[str, RobotFileParser] = {}

        self.session.headers.update(DEFAULT_HEADERS)
        self.session.headers["User-Agent"] = user_agent

    @abstractmethod
    def parse(self, html: str) -> ScrapedProduct:
        raise NotImplementedError

    def fetch(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ScraperError(f"Invalid URL: {url!r}")

        if self.respect_robots and not self._can_fetch(url):
            raise self._blocked_error(url, "robots.txt disallows this path")

        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            self._wait_between_requests()
            self._last_request_at = time.monotonic()

            try:
                response = self.session.get(url, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = exc
                if attempt == self.max_retries:
                    break
                self._backoff(attempt)
                continue

            if response.status_code in {401, 403, 429}:
                raise self._blocked_error(
                    url, f"HTTP {response.status_code} returned by the store"
                )

            if self._looks_like_block_page(response):
                raise self._blocked_error(url, "captcha or bot-check page detected")

            if response.status_code >= 500:
                last_error = ScraperError(
                    f"{self.store.value} returned HTTP {response.status_code} for {url}"
                )
                if attempt == self.max_retries:
                    break
                self._backoff(attempt)
                continue

            if response.status_code >= 400:
                raise ScraperError(
                    f"{self.store.value} returned HTTP {response.status_code} for {url}"
                )

            return response.text

        raise ScraperError(
            f"Failed to fetch {url} after {self.max_retries + 1} attempts"
        ) from last_error

    def _wait_between_requests(self) -> None:
        if self._last_request_at is None or self.delay_range[1] <= 0:
            return
        self._sleep(self._random(*self.delay_range))

    def _backoff(self, attempt: int) -> None:
        delay = self.backoff_factor * (2**attempt)
        if delay > 0:
            self._sleep(delay)

    def _can_fetch(self, url: str) -> bool:
        parser = self._robots_parser(url)
        return parser.can_fetch(self.user_agent, url)

    def _robots_parser(self, url: str) -> RobotFileParser:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"

        if origin in self._robots_cache:
            return self._robots_cache[origin]

        robots_url = f"{origin}/robots.txt"
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            self._wait_between_requests()
            self._last_request_at = time.monotonic()

            try:
                response = self.session.get(robots_url, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = exc
                if attempt == self.max_retries:
                    break
                self._backoff(attempt)
                continue

            if response.status_code in {401, 403, 429}:
                raise self._blocked_error(
                    url, f"robots.txt returned HTTP {response.status_code}"
                )

            if response.status_code >= 500:
                last_error = ScraperError(
                    f"Could not verify robots.txt for {origin}: "
                    f"HTTP {response.status_code}"
                )
                if attempt == self.max_retries:
                    break
                self._backoff(attempt)
                continue

            parser = RobotFileParser()
            parser.set_url(robots_url)
            if response.status_code >= 400:
                parser.parse([])
            else:
                parser.parse(response.text.splitlines())

            self._robots_cache[origin] = parser
            return parser

        raise ScraperError(
            f"Could not retrieve {robots_url} after {self.max_retries + 1} attempts"
        ) from last_error

    def _looks_like_block_page(self, response: requests.Response) -> bool:
        content_type = response.headers.get("Content-Type", "")
        if "html" not in content_type.lower():
            return False

        text = response.text[:50000].lower()
        return any(marker in text for marker in BLOCKED_PAGE_MARKERS)

    def _blocked_error(self, url: str, reason: str) -> ScraperBlockedError:
        return ScraperBlockedError(
            f"{self.store.value} blocked automated access to {url} ({reason}). "
            "No proxy or captcha bypass will be used. Use manually saved or "
            "archived pages, or replace this store with a scraper-friendly retailer."
        )


def extract_structured_product(soup: BeautifulSoup) -> StructuredProduct:
    product = _find_product_node(soup)
    if product is None:
        raise ScraperError(
            "No schema.org Product JSON-LD found; the page layout may have changed"
        )

    title = product.get("name")
    if not isinstance(title, str) or not title.strip():
        raise ScraperError(
            "Product title missing from structured data; the page layout may have changed"
        )

    image = _first_image(product.get("image"))
    if not image:
        raise ScraperError(
            "Product image missing from structured data; the page layout may have changed"
        )

    offer = _first_offer(product.get("offers"))
    if offer is None:
        raise ScraperError(
            "Product offer missing from structured data; the page layout may have changed"
        )

    price = _parse_price(offer.get("price", offer.get("lowPrice")))
    availability = offer.get("availability")

    return {
        "title": title.strip(),
        "price": price,
        "image_url": image,
        "in_stock": _parse_availability(availability),
    }


def infer_in_stock(soup: BeautifulSoup) -> bool:
    text = " ".join(soup.stripped_strings).lower()

    if any(marker in text for marker in OUT_OF_STOCK_MARKERS):
        return False
    if any(marker in text for marker in IN_STOCK_MARKERS):
        return True

    raise ScraperError(
        "Could not determine stock status; the page layout may have changed"
    )


def _find_product_node(soup: BeautifulSoup) -> dict | None:
    for node in _iter_json_ld(soup):
        if _has_type(node, "Product"):
            return node
    return None


def _iter_json_ld(soup: BeautifulSoup):
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        if not raw or not raw.strip():
            continue

        data = _decode_json(raw)
        if data is None:
            continue

        yield from _flatten_json_ld(data)


def _decode_json(raw: str):
    raw = raw.strip()
    try:
        return json.loads(raw, strict=False)
    except json.JSONDecodeError:
        try:
            data, _ = json.JSONDecoder(strict=False).raw_decode(raw)
            return data
        except json.JSONDecodeError:
            return None


def _flatten_json_ld(data):
    if isinstance(data, list):
        for item in data:
            yield from _flatten_json_ld(item)
        return

    if not isinstance(data, dict):
        return

    if "@graph" in data:
        yield from _flatten_json_ld(data["@graph"])
    if "@type" in data:
        yield data


def _has_type(node: dict, expected: str) -> bool:
    raw_type = node.get("@type")
    types = raw_type if isinstance(raw_type, list) else [raw_type]

    for value in types:
        if not isinstance(value, str):
            continue
        if value.rstrip("/").rsplit("/", 1)[-1].lower() == expected.lower():
            return True
    return False


def _first_image(value) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()
            if isinstance(item, dict) and isinstance(item.get("url"), str):
                return item["url"].strip() or None
    if isinstance(value, dict) and isinstance(value.get("url"), str):
        return value["url"].strip() or None
    return None


def _first_offer(value) -> dict | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                return item
    return None


def _parse_price(value) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ScraperError(
            "Product price missing from structured data; the page layout may have changed"
        )

    cleaned = str(value).replace(",", "").replace("₹", "").strip()
    try:
        price = Decimal(cleaned)
    except InvalidOperation:
        raise ScraperError(
            f"Invalid product price in structured data: {value!r}"
        ) from None

    if not price.is_finite() or price <= 0:
        raise ScraperError(f"Invalid product price in structured data: {value!r}")

    return price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _parse_availability(value) -> bool | None:
    if value is None:
        return None

    normalized = str(value).lower()
    if "outofstock" in normalized or "soldout" in normalized:
        return False
    if any(
        marker in normalized
        for marker in ("instock", "limitedavailability", "onlineonly", "instoreonly")
    ):
        return True
    return None

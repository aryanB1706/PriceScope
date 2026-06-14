from decimal import Decimal

import pytest

from app.scrapers import FlipkartScraper
from app.scrapers.base import ScraperError


def test_parses_flipkart_price_and_metadata(load_fixture):
    html = load_fixture("flipkart_in_stock_taupe.html")

    product = FlipkartScraper().parse(html)

    assert product["title"] == (
        "SONY WH-CH520 Wireless with 50 Hours Battery and Clear Calls Bluetooth"
    )
    assert product["price"] == Decimal("2990.00")
    assert product["image_url"].startswith("https://rukmini1.flixcart.com/")
    assert product["in_stock"] is True


def test_parses_a_second_flipkart_product_price(load_fixture):
    html = load_fixture("flipkart_in_stock_black.html")

    product = FlipkartScraper().parse(html)

    assert product["price"] == Decimal("2989.00")
    assert product["in_stock"] is True


def test_flipkart_out_of_stock(load_fixture):
    html = load_fixture("flipkart_in_stock_taupe.html")
    html = html.replace("schema.org\\u002fInStock", "schema.org\\u002fOutOfStock")
    html = html.replace(
        '"availability":"https://schema.org/InStock"',
        '"availability":"https://schema.org/OutOfStock"',
    )

    product = FlipkartScraper().parse(html)

    assert product["in_stock"] is False


def test_flipkart_missing_structured_data_raises(load_fixture, without_json_ld):
    html = without_json_ld(load_fixture("flipkart_in_stock_taupe.html"))

    with pytest.raises(ScraperError, match="schema.org Product JSON-LD"):
        FlipkartScraper().parse(html)

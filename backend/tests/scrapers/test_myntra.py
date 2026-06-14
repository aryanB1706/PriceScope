from decimal import Decimal

import pytest

from app.scrapers import MyntraScraper
from app.scrapers.base import ScraperError


def test_parses_myntra_price_and_metadata(load_fixture):
    html = load_fixture("myntra_in_stock_celio.html")

    product = MyntraScraper().parse(html)

    assert product["title"] == "Celio Men Red Cotton T-shirt"
    assert product["price"] == Decimal("934.00")
    assert product["image_url"].startswith("https://assets.myntassets.com/")
    assert product["in_stock"] is True


def test_parses_myntra_out_of_stock(load_fixture):
    html = load_fixture("myntra_out_of_stock_tommy.html")

    product = MyntraScraper().parse(html)

    assert product["title"] == (
        "Tommy Hilfiger Men White & Navy blue Striped Round Neck T-shirt"
    )
    assert product["price"] == Decimal("2599.00")
    assert product["in_stock"] is False


def test_myntra_missing_structured_data_raises(load_fixture, without_json_ld):
    html = without_json_ld(load_fixture("myntra_in_stock_celio.html"))

    with pytest.raises(ScraperError, match="schema.org Product JSON-LD"):
        MyntraScraper().parse(html)

from decimal import Decimal

import pytest

from app.scrapers import CromaScraper
from app.scrapers.base import ScraperError


def test_parses_croma_price_and_metadata(load_fixture):
    html = load_fixture("croma_in_stock_tcl.html")

    product = CromaScraper().parse(html)

    assert product["title"] == (
        "TCL V6C 140 cm (55 inch) 4 Star 4K Ultra HD LED Smart Google TV "
        "with Google Voice Assistant (2025 model)"
    )
    assert product["price"] == Decimal("34990.00")
    assert product["image_url"].startswith("https://media.tatacroma.com/")
    assert product["in_stock"] is True


def test_parses_a_second_croma_product_price(load_fixture):
    html = load_fixture("croma_in_stock_samsung.html")

    product = CromaScraper().parse(html)

    assert product["price"] == Decimal("111090.00")
    assert product["in_stock"] is True


def test_croma_out_of_stock_from_page_state(load_fixture):
    html = load_fixture("croma_in_stock_tcl.html")
    html = html.replace("Buy Now", "Out of Stock").replace(
        "Add to Cart", "Notify Me"
    )

    product = CromaScraper().parse(html)

    assert product["in_stock"] is False


def test_croma_missing_structured_data_raises(load_fixture, without_json_ld):
    html = without_json_ld(load_fixture("croma_in_stock_tcl.html"))

    with pytest.raises(ScraperError, match="schema.org Product JSON-LD"):
        CromaScraper().parse(html)

import pytest

from app.scrapers import (
    CromaScraper,
    FlipkartScraper,
    MyntraScraper,
    ScraperError,
    get_scraper,
)


@pytest.mark.parametrize(
    ("url", "expected_class"),
    [
        ("https://www.flipkart.com/item", FlipkartScraper),
        ("https://www.myntra.com/tshirts/item/1/buy", MyntraScraper),
        ("https://www.croma.com/item/p/123", CromaScraper),
        ("https://flipkart.com/item", FlipkartScraper),
    ],
)
def test_get_scraper_selects_by_domain(url, expected_class):
    assert isinstance(get_scraper(url), expected_class)


def test_get_scraper_rejects_unknown_domain():
    with pytest.raises(ScraperError, match="No scraper registered"):
        get_scraper("https://www.amazon.in/item")


def test_get_scraper_does_not_match_spoofed_domains():
    with pytest.raises(ScraperError, match="No scraper registered"):
        get_scraper("https://flipkart.com.evil.example/item")

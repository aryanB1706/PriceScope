from bs4 import BeautifulSoup

from app.models import Store
from app.scrapers.base import (
    BaseScraper,
    ScraperError,
    ScrapedProduct,
    extract_structured_product,
)


class FlipkartScraper(BaseScraper):
    store = Store.FLIPKART

    def parse(self, html: str) -> ScrapedProduct:
        soup = BeautifulSoup(html, "html.parser")
        product = extract_structured_product(soup)

        if product["in_stock"] is None:
            raise ScraperError(
                "Flipkart stock availability missing from structured data; "
                "the page layout may have changed"
            )

        return {
            "title": product["title"],
            "price": product["price"],
            "image_url": product["image_url"],
            "in_stock": product["in_stock"],
        }

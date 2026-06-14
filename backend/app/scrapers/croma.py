from bs4 import BeautifulSoup

from app.models import Store
from app.scrapers.base import (
    BaseScraper,
    ScrapedProduct,
    extract_structured_product,
    infer_in_stock,
)


class CromaScraper(BaseScraper):
    store = Store.CROMA

    def parse(self, html: str) -> ScrapedProduct:
        soup = BeautifulSoup(html, "html.parser")
        product = extract_structured_product(soup)

        in_stock = product["in_stock"]
        if in_stock is None:
            in_stock = infer_in_stock(soup)

        return {
            "title": product["title"],
            "price": product["price"],
            "image_url": product["image_url"],
            "in_stock": in_stock,
        }

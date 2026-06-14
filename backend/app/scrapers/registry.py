from urllib.parse import urlparse

from app.scrapers.base import BaseScraper, ScraperError
from app.scrapers.croma import CromaScraper
from app.scrapers.flipkart import FlipkartScraper
from app.scrapers.myntra import MyntraScraper

SCRAPER_REGISTRY: dict[str, type[BaseScraper]] = {
    "flipkart.com": FlipkartScraper,
    "myntra.com": MyntraScraper,
    "croma.com": CromaScraper,
}


def get_scraper(url: str, **options) -> BaseScraper:
    hostname = (urlparse(url).hostname or "").lower()

    for domain, scraper_class in SCRAPER_REGISTRY.items():
        if hostname == domain or hostname.endswith(f".{domain}"):
            return scraper_class(**options)

    raise ScraperError(f"No scraper registered for domain: {hostname or url!r}")

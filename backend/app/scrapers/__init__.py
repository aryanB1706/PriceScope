from app.scrapers.base import (
    BaseScraper,
    ScrapedProduct,
    ScraperBlockedError,
    ScraperError,
)
from app.scrapers.croma import CromaScraper
from app.scrapers.flipkart import FlipkartScraper
from app.scrapers.myntra import MyntraScraper
from app.scrapers.registry import SCRAPER_REGISTRY, get_scraper, scraper_class_for

__all__ = [
    "BaseScraper",
    "CromaScraper",
    "FlipkartScraper",
    "MyntraScraper",
    "SCRAPER_REGISTRY",
    "ScrapedProduct",
    "ScraperBlockedError",
    "ScraperError",
    "get_scraper",
    "scraper_class_for",
]

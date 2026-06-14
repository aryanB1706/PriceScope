import pytest
import requests

from app.models import Store
from app.scrapers.base import (
    BaseScraper,
    ScraperBlockedError,
    ScraperError,
    ScrapedProduct,
)


class FakeResponse:
    def __init__(self, status_code: int, text: str = "", content_type="text/html"):
        self.status_code = status_code
        self.text = text
        self.headers = {"Content-Type": content_type}


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = {"User-Agent": "python-requests/2.34.2"}

    def get(self, url, **kwargs):
        self.calls.append(url)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class DummyScraper(BaseScraper):
    store = Store.FLIPKART

    def parse(self, html: str) -> ScrapedProduct:
        return {
            "title": "Test product",
            "price": 1,
            "image_url": "https://example.com/image.jpg",
            "in_stock": True,
        }


def make_scraper(session, **options):
    defaults = {
        "session": session,
        "respect_robots": False,
        "delay_range": (0, 0),
        "backoff_factor": 0,
    }
    defaults.update(options)
    return DummyScraper(**defaults)


def test_fetch_returns_html_and_sets_realistic_user_agent():
    session = FakeSession(FakeResponse(200, "<html>ok</html>"))

    html = make_scraper(session).fetch("https://www.flipkart.com/item")

    assert html == "<html>ok</html>"
    assert "Mozilla/5.0" in session.headers["User-Agent"]
    assert "python-requests" not in session.headers["User-Agent"]
    assert len(session.calls) == 1


def test_fetch_retries_server_errors_with_exponential_backoff():
    session = FakeSession(
        FakeResponse(500, "error"),
        FakeResponse(503, "error"),
        FakeResponse(200, "ok"),
    )
    sleeps = []
    scraper = make_scraper(
        session,
        max_retries=2,
        backoff_factor=0.5,
        sleeper=sleeps.append,
    )

    assert scraper.fetch("https://www.flipkart.com/item") == "ok"
    assert len(session.calls) == 3
    assert sleeps == [0.5, 1.0]


def test_fetch_does_not_retry_when_blocked():
    session = FakeSession(FakeResponse(403, "Access Denied"))
    scraper = make_scraper(session)

    with pytest.raises(ScraperBlockedError, match="No proxy or captcha bypass"):
        scraper.fetch("https://www.flipkart.com/item")

    assert len(session.calls) == 1


def test_fetch_detects_captcha_page_returned_with_200():
    session = FakeSession(
        FakeResponse(200, "<html><body>Verify you are human</body></html>")
    )
    scraper = make_scraper(session)

    with pytest.raises(ScraperBlockedError, match="bot-check page detected"):
        scraper.fetch("https://www.flipkart.com/item")

    assert len(session.calls) == 1


def test_fetch_retries_network_errors():
    session = FakeSession(
        requests.Timeout("timed out"),
        FakeResponse(200, "ok"),
    )
    scraper = make_scraper(session, max_retries=1)

    assert scraper.fetch("https://www.flipkart.com/item") == "ok"
    assert len(session.calls) == 2


def test_fetch_waits_one_to_three_seconds_between_requests():
    session = FakeSession(FakeResponse(200, "one"), FakeResponse(200, "two"))
    sleeps = []
    scraper = make_scraper(
        session,
        delay_range=(1.0, 3.0),
        randomizer=lambda low, high: 2.5,
        sleeper=sleeps.append,
    )

    assert scraper.fetch("https://www.flipkart.com/one") == "one"
    assert scraper.fetch("https://www.flipkart.com/two") == "two"
    assert sleeps == [2.5]


def test_fetch_respects_robots_txt_disallow():
    session = FakeSession(
        FakeResponse(200, "User-agent: *\nDisallow: /blocked"),
        FakeResponse(200, "should not be fetched"),
    )
    scraper = make_scraper(session, respect_robots=True)

    with pytest.raises(ScraperBlockedError, match="robots.txt"):
        scraper.fetch("https://www.flipkart.com/blocked")

    assert session.calls == ["https://www.flipkart.com/robots.txt"]


def test_fetch_refuses_when_robots_txt_is_forbidden():
    session = FakeSession(FakeResponse(403, "Access Denied"))
    scraper = make_scraper(session, respect_robots=True)

    with pytest.raises(ScraperBlockedError, match="robots.txt returned HTTP 403"):
        scraper.fetch("https://www.flipkart.com/item")


def test_robots_fetch_retries_network_errors():
    session = FakeSession(
        requests.Timeout("timed out"),
        FakeResponse(200, "User-agent: *\nAllow: /"),
        FakeResponse(200, "product page"),
    )
    scraper = make_scraper(session, respect_robots=True, max_retries=1)

    assert scraper.fetch("https://www.flipkart.com/item") == "product page"
    assert session.calls == [
        "https://www.flipkart.com/robots.txt",
        "https://www.flipkart.com/robots.txt",
        "https://www.flipkart.com/item",
    ]


def test_fetch_raises_clear_error_after_retry_exhaustion():
    session = FakeSession(
        FakeResponse(500, "error"),
        FakeResponse(500, "error"),
    )
    scraper = make_scraper(session, max_retries=1)

    with pytest.raises(ScraperError, match="after 2 attempts"):
        scraper.fetch("https://www.flipkart.com/item")

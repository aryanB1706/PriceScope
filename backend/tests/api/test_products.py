from datetime import datetime, timezone
from decimal import Decimal

import pytest
from bson import ObjectId

from app.scrapers import ScraperBlockedError, ScraperError
from tests.api.conftest import FLIPKART_URL, MYNTRA_URL


def post_product(api, headers, **body):
    return api.post("/api/products", json=body, headers=headers)


def test_add_product_creates_product_watch_and_first_price(api, db, scraper, alice):
    response = post_product(
        api, alice, url=FLIPKART_URL, target_price=899.5, alert_on_30d_low=True
    )

    assert response.status_code == 201
    data = response.get_json()
    assert data["product"]["title"] == "Sony Headphones"
    assert data["product"]["store"] == "flipkart"
    assert data["product"]["current_price"] == 1000.0
    assert data["watch"]["target_price"] == 899.5
    assert data["watch"]["alert_on_30d_low"] is True

    assert db.products.count_documents({}) == 1
    assert db.price_history.count_documents({}) == 1
    watch = db.watches.find_one({})
    assert watch["user_id"] == "alice"
    assert str(watch["_id"]) == data["watch"]["id"]


def test_add_product_defaults_to_no_target_and_no_low_alert(api, scraper, alice):
    data = post_product(api, alice, url=MYNTRA_URL).get_json()

    assert data["watch"]["target_price"] is None
    assert data["watch"]["alert_on_30d_low"] is False


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"url": "not a url"},
        {"url": 123},
        {"url": "ftp://www.flipkart.com/item"},
        {"url": "https://www.amazon.in/item"},
        {"url": "https://flipkart.com.evil.example/item"},
        {"url": FLIPKART_URL, "target_price": -5},
        {"url": FLIPKART_URL, "target_price": 0},
        {"url": FLIPKART_URL, "target_price": "cheap"},
        {"url": FLIPKART_URL, "target_price": True},
        {"url": FLIPKART_URL, "alert_on_30d_low": "yes"},
        {"url": FLIPKART_URL, "surprise": 1},
    ],
)
def test_add_product_rejects_invalid_input(api, db, scraper, alice, body):
    response = post_product(api, alice, **body)

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] in {
        "invalid_request",
        "unsupported_store",
    }
    assert scraper.created == 0
    assert db.products.count_documents({}) == 0
    assert db.watches.count_documents({}) == 0


def test_unsupported_store_has_its_own_error_code(api, scraper, alice):
    response = post_product(api, alice, url="https://www.amazon.in/item")

    assert response.get_json()["error"]["code"] == "unsupported_store"


def test_add_product_requires_json_object_body(api, alice):
    not_json = api.post("/api/products", data="url=x", headers=alice)
    a_list = api.post("/api/products", json=[FLIPKART_URL], headers=alice)

    assert not_json.status_code == 400
    assert a_list.status_code == 400


def test_scrape_failure_returns_502_and_creates_nothing(api, db, scraper, alice):
    scraper.error = ScraperBlockedError("blocked")

    response = post_product(api, alice, url=FLIPKART_URL)

    assert response.status_code == 502
    assert response.get_json()["error"]["code"] == "scrape_failed"
    assert db.products.count_documents({}) == 0
    assert db.watches.count_documents({}) == 0


def test_watching_the_same_product_twice_returns_409_without_scraping(
    api, db, scraper, alice
):
    post_product(api, alice, url=FLIPKART_URL)
    scrapes_before = scraper.created

    response = post_product(api, alice, url=FLIPKART_URL)

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "already_watching"
    assert scraper.created == scrapes_before
    assert db.watches.count_documents({}) == 1


def test_two_users_share_one_product_but_have_separate_watches(
    api, db, scraper, alice, bob
):
    post_product(api, alice, url=FLIPKART_URL, target_price=500)
    response = post_product(api, bob, url=FLIPKART_URL, target_price=900)

    assert response.status_code == 201
    assert db.products.count_documents({}) == 1
    assert db.watches.count_documents({}) == 2


def test_list_products_is_empty_for_new_user(api, alice):
    response = api.get("/api/products", headers=alice)

    assert response.status_code == 200
    assert response.get_json() == {"products": []}


def test_list_products_returns_only_own_watches_with_stats(
    api, make_product, make_watch, add_history, alice, bob
):
    cheap = make_product(url=FLIPKART_URL, price="800", title="Headphones")
    other = make_product(url=MYNTRA_URL, price="500", title="T-shirt")
    for days_ago, price in [(20, "1200"), (10, "900"), (0, "800")]:
        add_history(cheap, price, days_ago)
    add_history(other, "500", 1)
    make_watch("alice", cheap, target_price="700")
    make_watch("bob", other)

    mine = api.get("/api/products", headers=alice).get_json()["products"]
    theirs = api.get("/api/products", headers=bob).get_json()["products"]

    assert [p["title"] for p in mine] == ["Headphones"]
    assert [p["title"] for p in theirs] == ["T-shirt"]
    item = mine[0]
    assert item["current_price"] == 800.0
    assert item["lowest_price"] == 800.0
    assert item["highest_price"] == 1200.0
    assert item["is_30d_low"] is True
    assert item["in_stock"] is True
    assert item["watch"]["target_price"] == 700.0
    assert item["product_id"] == item["id"]


def test_list_products_flags_price_that_is_not_a_30d_low(
    api, make_product, make_watch, add_history, alice
):
    product = make_product(price="1000")
    add_history(product, "700", 15)
    add_history(product, "1000", 0)
    make_watch("alice", product)

    item = api.get("/api/products", headers=alice).get_json()["products"][0]

    assert item["is_30d_low"] is False
    assert item["lowest_price"] == 700.0


def test_history_returns_points_and_stats(
    api, make_product, make_watch, add_history, alice
):
    product = make_product()
    add_history(product, "1100", 40)  # outside the 30-day window
    add_history(product, "900", 10)
    add_history(product, "1000", 2)
    make_watch("alice", product)

    response = api.get(f"/api/products/{product}/history?days=30", headers=alice)

    assert response.status_code == 200
    data = response.get_json()
    assert [p["price"] for p in data["points"]] == [900.0, 1000.0]
    assert data["min_price"] == 900.0
    assert data["max_price"] == 1000.0
    assert data["current_price"] == 1000.0
    assert data["days"] == 30


@pytest.mark.parametrize("days", ["0", "-3", "abc", "366", ""])
def test_history_rejects_invalid_days(api, make_product, make_watch, alice, days):
    product = make_product()
    make_watch("alice", product)

    response = api.get(f"/api/products/{product}/history?days={days}", headers=alice)

    assert response.status_code == 400


def test_history_of_unwatched_product_is_404(
    api, make_product, make_watch, add_history, alice, bob
):
    product = make_product()
    add_history(product, "900", 1)
    make_watch("bob", product)

    response = api.get(f"/api/products/{product}/history", headers=alice)

    assert response.status_code == 404


@pytest.mark.parametrize("product_id", ["nope", str(ObjectId())])
def test_history_of_unknown_product_is_404(api, alice, product_id):
    response = api.get(f"/api/products/{product_id}/history", headers=alice)

    assert response.status_code == 404

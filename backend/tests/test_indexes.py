import mongomock
from pymongo import ASCENDING, DESCENDING

from app.models import init_db


def test_init_db_creates_indexes_and_can_run_twice():
    db = mongomock.MongoClient(tz_aware=True).pricescope_test

    init_db(db)
    init_db(db)

    product_indexes = db.products.index_information()
    assert product_indexes["products_url_unique"]["key"] == [("url", ASCENDING)]
    assert product_indexes["products_url_unique"]["unique"] is True

    history_indexes = db.price_history.index_information()
    assert history_indexes["price_history_product_scraped_at"]["key"] == [
        ("product_id", ASCENDING),
        ("scraped_at", DESCENDING),
    ]

    watch_indexes = db.watches.index_information()
    assert watch_indexes["watches_user_product_unique"]["key"] == [
        ("user_id", ASCENDING),
        ("product_id", ASCENDING),
    ]
    assert watch_indexes["watches_user_product_unique"]["unique"] is True

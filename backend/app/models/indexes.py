from pymongo import ASCENDING, DESCENDING
from pymongo.database import Database

PRODUCTS_URL_INDEX = "products_url_unique"
PRICE_HISTORY_PRODUCT_SCRAPED_INDEX = "price_history_product_scraped_at"
WATCHES_USER_PRODUCT_INDEX = "watches_user_product_unique"


def init_db(db: Database) -> None:
    db.products.create_index("url", unique=True, name=PRODUCTS_URL_INDEX)
    db.price_history.create_index(
        [("product_id", ASCENDING), ("scraped_at", DESCENDING)],
        name=PRICE_HISTORY_PRODUCT_SCRAPED_INDEX,
    )
    db.watches.create_index(
        [("user_id", ASCENDING), ("product_id", ASCENDING)],
        unique=True,
        name=WATCHES_USER_PRODUCT_INDEX,
    )

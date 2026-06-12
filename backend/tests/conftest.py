import pytest

from app import create_app


@pytest.fixture
def app():
    return create_app(
        {
            "TESTING": True,
            "MONGO_URI": "mongodb://localhost:27017/",
            "MONGO_DB_NAME": "pricescope_test",
            "MONGO_SERVER_SELECTION_TIMEOUT_MS": 100,
        }
    )


@pytest.fixture
def client(app):
    return app.test_client()

from pymongo.errors import ServerSelectionTimeoutError


def test_health_when_mongo_is_reachable(client, monkeypatch):
    monkeypatch.setattr("app.routes.health.ping_db", lambda: True)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "database": "ok"}


def test_health_when_mongo_is_unreachable(client, monkeypatch):
    def raise_timeout():
        raise ServerSelectionTimeoutError("MongoDB is unavailable")

    monkeypatch.setattr("app.routes.health.ping_db", raise_timeout)

    response = client.get("/api/health")

    assert response.status_code == 503
    assert response.get_json() == {"status": "error", "database": "unavailable"}

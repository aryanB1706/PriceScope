import pytest
from firebase_admin import exceptions

PROTECTED = [
    ("get", "/api/products"),
    ("post", "/api/products"),
    ("get", "/api/products/65a000000000000000000000/history"),
    ("patch", "/api/watches/65a000000000000000000000"),
    ("delete", "/api/watches/65a000000000000000000000"),
    ("get", "/api/alerts"),
]


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_protected_routes_require_a_token(api, method, path):
    response = getattr(api, method)(path)

    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize("header", ["Basic abc", "Bearer", "Bearer   ", "token-alice"])
def test_malformed_authorization_header_is_rejected(api, header):
    response = api.get("/api/products", headers={"Authorization": header})

    assert response.status_code == 401


def test_invalid_token_is_rejected(api):
    response = api.get("/api/products", headers={"Authorization": "Bearer forged"})

    assert response.status_code == 401
    assert response.get_json() == {
        "error": {"code": "unauthorized", "message": "Invalid or expired token"}
    }


def test_firebase_outage_returns_503(api, monkeypatch):
    def unavailable(token):
        raise exceptions.UnavailableError("certs unreachable")

    monkeypatch.setattr("app.services.auth.verify_firebase_token", unavailable)

    response = api.get("/api/products", headers={"Authorization": "Bearer x"})

    assert response.status_code == 503
    assert response.get_json()["error"]["code"] == "auth_unavailable"


def test_health_check_does_not_require_auth(api, monkeypatch):
    monkeypatch.setattr("app.routes.health.ping_db", lambda: True)

    assert api.get("/api/health").status_code == 200


def test_unknown_route_returns_json_error(api):
    response = api.get("/api/nope")

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "not_found"


def test_wrong_method_returns_json_error(api, alice):
    response = api.put("/api/products", headers=alice)

    assert response.status_code == 405
    assert "error" in response.get_json()


def test_cors_allows_only_the_frontend_origin(api, alice):
    allowed = api.get(
        "/api/products", headers={**alice, "Origin": "http://localhost:5173"}
    )
    other = api.get("/api/products", headers={**alice, "Origin": "https://evil.example"})

    assert allowed.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert "Access-Control-Allow-Origin" not in other.headers


def test_cors_preflight_needs_no_token(api):
    response = api.options(
        "/api/products",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code in {200, 204}
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert "Authorization" in response.headers["Access-Control-Allow-Headers"]

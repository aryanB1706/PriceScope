from bson import ObjectId
from bson.decimal128 import Decimal128
import pytest


def test_patch_updates_target_price_and_alert_flag(
    api, db, make_product, make_watch, alice
):
    watch_id = make_watch("alice", make_product())

    response = api.patch(
        f"/api/watches/{watch_id}",
        json={"target_price": 750.25, "alert_on_30d_low": True},
        headers=alice,
    )

    assert response.status_code == 200
    watch = response.get_json()["watch"]
    assert watch["target_price"] == 750.25
    assert watch["alert_on_30d_low"] is True
    stored = db.watches.find_one({"_id": watch_id})
    assert stored["target_price"] == Decimal128("750.25")


def test_patch_with_null_clears_target_price(api, make_product, make_watch, alice):
    watch_id = make_watch("alice", make_product(), target_price="500")

    response = api.patch(
        f"/api/watches/{watch_id}", json={"target_price": None}, headers=alice
    )

    assert response.status_code == 200
    assert response.get_json()["watch"]["target_price"] is None


def test_patch_only_changes_the_provided_fields(api, make_product, make_watch, alice):
    watch_id = make_watch("alice", make_product(), target_price="500")

    watch = api.patch(
        f"/api/watches/{watch_id}", json={"alert_on_30d_low": True}, headers=alice
    ).get_json()["watch"]

    assert watch["target_price"] == 500.0
    assert watch["alert_on_30d_low"] is True


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"target_price": -1},
        {"target_price": "free"},
        {"alert_on_30d_low": 1},
        {"user_id": "bob"},
        {"product_id": "65a000000000000000000000"},
    ],
)
def test_patch_rejects_invalid_input(api, db, make_product, make_watch, alice, body):
    watch_id = make_watch("alice", make_product(), target_price="500")

    response = api.patch(f"/api/watches/{watch_id}", json=body, headers=alice)

    assert response.status_code == 400
    stored = db.watches.find_one({"_id": watch_id})
    assert stored["user_id"] == "alice"
    assert stored["target_price"] == Decimal128("500.00")


def test_patch_other_users_watch_is_404_and_changes_nothing(
    api, db, make_product, make_watch, bob
):
    watch_id = make_watch("alice", make_product(), target_price="500")

    response = api.patch(
        f"/api/watches/{watch_id}", json={"target_price": 1}, headers=bob
    )

    assert response.status_code == 404
    assert db.watches.find_one({"_id": watch_id})["target_price"] == Decimal128("500.00")


def test_patch_unknown_or_malformed_watch_id_is_404(api, alice):
    for watch_id in [str(ObjectId()), "not-an-id"]:
        response = api.patch(
            f"/api/watches/{watch_id}", json={"target_price": 5}, headers=alice
        )
        assert response.status_code == 404


def test_delete_removes_own_watch_but_keeps_product(
    api, db, make_product, make_watch, alice
):
    product_id = make_product()
    watch_id = make_watch("alice", product_id)

    response = api.delete(f"/api/watches/{watch_id}", headers=alice)

    assert response.status_code == 204
    assert response.data == b""
    assert db.watches.count_documents({}) == 0
    assert db.products.count_documents({"_id": product_id}) == 1


def test_delete_other_users_watch_is_404_and_keeps_it(
    api, db, make_product, make_watch, bob
):
    watch_id = make_watch("alice", make_product())

    response = api.delete(f"/api/watches/{watch_id}", headers=bob)

    assert response.status_code == 404
    assert db.watches.count_documents({"_id": watch_id}) == 1


def test_delete_malformed_watch_id_is_404(api, alice):
    assert api.delete("/api/watches/not-an-id", headers=alice).status_code == 404


def test_alerts_are_scoped_to_user_newest_first_with_product_info(
    api, make_product, add_alert, alice
):
    product_id = make_product(title="Sony Headphones")
    add_alert("alice", product_id, "900", minutes_ago=60)
    add_alert("alice", product_id, "850", minutes_ago=5)
    add_alert("bob", product_id, "100", minutes_ago=1)

    response = api.get("/api/alerts", headers=alice)

    assert response.status_code == 200
    alerts = response.get_json()["alerts"]
    assert [a["new_price"] for a in alerts] == [850.0, 900.0]
    assert alerts[0]["product_title"] == "Sony Headphones"
    assert alerts[0]["reason"] == "target_price"
    assert alerts[0]["old_price"] == 1000.0
    assert alerts[0]["email_status"] == "pending"


def test_alerts_limit_is_applied_and_validated(api, make_product, add_alert, alice):
    product_id = make_product()
    for minutes in range(5):
        add_alert("alice", product_id, "900", minutes_ago=minutes)

    limited = api.get("/api/alerts?limit=2", headers=alice).get_json()["alerts"]

    assert len(limited) == 2
    assert api.get("/api/alerts?limit=0", headers=alice).status_code == 400
    assert api.get("/api/alerts?limit=abc", headers=alice).status_code == 400


def test_alerts_empty_for_user_without_alerts(api, alice):
    assert api.get("/api/alerts", headers=alice).get_json() == {"alerts": []}

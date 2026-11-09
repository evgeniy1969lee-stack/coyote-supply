import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from backend.app.demo_data import load_demo
from backend.app.main import create_app
from backend.app.schemas import MAX_SAFE_INTEGER

DOCS = Path(__file__).resolve().parents[2] / "docs"
SCHEMA = json.loads((DOCS / "api-schema.json").read_text(encoding="utf-8"))
SHYMKENT = "/api/stores/shymkent-demo"
ALMATY = "/api/stores/almaty-demo"


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "drafts.sqlite3")) as test_client:
        yield test_client


def check_schema(response, schema_name, status=200):
    assert response.status_code == status, response.text
    assert response.headers["content-type"] == "application/json"
    body = response.json()
    schema = SCHEMA | {"$ref": f"#/$defs/{schema_name}"}
    Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER).validate(body)
    return body


def fixture(path):
    return json.loads((DOCS / "fixtures" / path).read_text(encoding="utf-8"))


def draft_request(client, url=SHYMKENT, quantity=30000):
    forecast = client.get(f"{url}/forecast").json()
    return {"forecastId": forecast["forecastId"], "rows": [{"ingredientId": "milk", "quantity": quantity}]}


def test_api_success_responses_and_control_fixtures(client):
    assert check_schema(client.get("/api/health"), "health") == {"status": "ok"}
    assert check_schema(client.get("/api/stores"), "stores") == fixture("stores.json")
    for store_id in ("shymkent-demo", "almaty-demo"):
        forecast = check_schema(client.get(f"/api/stores/{store_id}/forecast"), "forecast")
        expected = fixture(f"{store_id}/forecast.json")
        assert {k: v for k, v in forecast.items() if k not in ("forecastId", "ingredients")} == {
            k: v for k, v in expected.items() if k not in ("forecastId", "ingredients")
        }
        actual_items = {item["ingredientId"]: item for item in forecast["ingredients"]}
        assert len(actual_items) == 7
        for item in expected["ingredients"]:
            assert actual_items[item["ingredientId"]] == item

    assert check_schema(client.get(f"{ALMATY}/draft"), "draftResponse") == fixture(
        "almaty-demo/draft-empty.json",
    )
    response = client.put(f"{SHYMKENT}/draft", json=draft_request(client, quantity=24000))
    assert check_schema(response, "draftResponse")["draft"]["totalKzt"] == 16800
    response = client.put(f"{SHYMKENT}/draft", json=draft_request(client))
    saved = check_schema(response, "draftResponse")
    assert saved["draft"]["rows"] == fixture("shymkent-demo/draft-saved.json")["draft"]["rows"]
    assert saved["draft"]["totalKzt"] == 21000
    assert client.get(f"{SHYMKENT}/draft").json() == saved


def test_drafts_survive_restart_are_isolated_and_clear_idempotently(tmp_path, monkeypatch):
    db = tmp_path / "nested" / "drafts.sqlite3"
    monkeypatch.setenv("COYOTE_DB_PATH", str(db))
    with TestClient(create_app()) as first:
        request = draft_request(first)
        saved = check_schema(first.put(f"{SHYMKENT}/draft", json=request), "draftResponse")
        other_request = draft_request(first, ALMATY, quantity=12000)
        other = check_schema(first.put(f"{ALMATY}/draft", json=other_request), "draftResponse")

    with TestClient(create_app()) as restarted:
        assert restarted.get(f"{SHYMKENT}/draft").json() == saved
        assert restarted.get(f"{ALMATY}/draft").json() == other
        assert draft_request(restarted) == request
        for _ in range(2):
            assert check_schema(restarted.put(
                f"{SHYMKENT}/draft", json=request | {"rows": []},
            ), "draftResponse")["draft"] is None
        assert restarted.get(f"{SHYMKENT}/draft").json()["draft"] is None
        assert restarted.get(f"{ALMATY}/draft").json() == other
    assert db.is_file()


def test_new_snapshot_rejects_stale_write_but_still_serves_saved_draft(tmp_path):
    db = tmp_path / "drafts.sqlite3"
    with TestClient(create_app(db)) as first:
        request = draft_request(first)
        saved = first.put(f"{SHYMKENT}/draft", json=request).json()

    demo = load_demo()
    demo.catalog["milk"].pack_price_kzt += 1
    with TestClient(create_app(db, dataset=demo)) as second:
        assert second.get(f"{SHYMKENT}/draft").json() == saved
        assert draft_request(second)["forecastId"] != request["forecastId"]
        result = check_schema(second.put(f"{SHYMKENT}/draft", json=request), "error", 409)
        assert result == fixture("error-stale-forecast.json")
        assert second.get(f"{SHYMKENT}/draft").json() == saved


@pytest.mark.parametrize(("method", "suffix"), [("GET", "forecast"), ("GET", "draft"), ("PUT", "draft")])
def test_unknown_store(client, method, suffix):
    result = client.request(method, f"/api/stores/unknown/{suffix}", json=draft_request(client))
    assert check_schema(result, "error", 404)["error"]["code"] == "store_not_found"


@pytest.mark.parametrize(("rows", "path", "reason"), [
    ([{"ingredientId": "milk", "quantity": 25000}], "rows.0.quantity", "not_multiple_of_pack"),
    ([{"ingredientId": "milk", "quantity": 0}], "rows.0.quantity", "greater_than"),
    ([{"ingredientId": "milk", "quantity": -6000}], "rows.0.quantity", "greater_than"),
    ([{"ingredientId": "milk", "quantity": 6000.0}], "rows.0.quantity", "int_type"),
    ([{"ingredientId": "milk", "quantity": "6000"}], "rows.0.quantity", "int_type"),
    ([{"ingredientId": "milk", "quantity": True}], "rows.0.quantity", "int_type"),
    ([{"ingredientId": "milk", "quantity": MAX_SAFE_INTEGER + 1}], "rows.0.quantity", "less_than_equal"),
    ([{"ingredientId": "cups", "quantity": MAX_SAFE_INTEGER // 50 * 50}], "rows.0.quantity", "amount_out_of_range"),
    ([{"ingredientId": "milk", "quantity": 6000, "packPriceKzt": 1}], "rows.0.packPriceKzt", "extra_forbidden"),
    ([{"ingredientId": "unknown", "quantity": 6000}], "rows.0.ingredientId", "unknown_ingredient"),
    ([{"ingredientId": "oat-milk", "quantity": 6000}], "rows.0.ingredientId", "recommendation_unavailable"),
    ([{"ingredientId": "milk", "quantity": 6000}] * 2, "rows.1.ingredientId", "duplicate_ingredient"),
])
def test_invalid_draft_keeps_existing_snapshot(client, rows, path, reason):
    request = draft_request(client)
    saved = client.put(f"{SHYMKENT}/draft", json=request).json()
    response = client.put(f"{SHYMKENT}/draft", json=request | {"rows": rows})
    error = check_schema(response, "error", 422)["error"]
    assert error["code"] == "invalid_draft"
    assert {"path": path, "reason": reason} in error["details"]
    assert client.get(f"{SHYMKENT}/draft").json() == saved


def test_zero_recommendation_can_be_manually_added_and_replaces_old_rows(client):
    request = draft_request(client)
    client.put(f"{SHYMKENT}/draft", json=request).raise_for_status()
    rows = [{"ingredientId": "cups", "quantity": 100}]
    response = client.put(f"{SHYMKENT}/draft", json=request | {"rows": rows})
    assert check_schema(response, "draftResponse")["draft"]["rows"] == [{
        "ingredientId": "cups", "quantity": 100, "packCount": 2, "packPriceKzt": 1800,
        "lineTotalKzt": 3600,
    }]


def test_sqlite_failure_rolls_back_draft_replacement(tmp_path):
    db = tmp_path / "drafts.sqlite3"
    with TestClient(create_app(db), raise_server_exceptions=False) as client:
        request = draft_request(client)
        saved = client.put(f"{SHYMKENT}/draft", json=request).json()
        with closing(sqlite3.connect(db)) as connection, connection:
            connection.execute("""
                CREATE TRIGGER fail_update AFTER UPDATE ON drafts
                BEGIN SELECT RAISE(ABORT, 'simulated write failure'); END
            """)
        assert client.put(f"{SHYMKENT}/draft", json=draft_request(client, quantity=6000)).status_code == 500
        assert client.get(f"{SHYMKENT}/draft").json() == saved


def test_cors_preflight_and_malformed_json(client):
    response = client.options(f"{SHYMKENT}/draft", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "PUT",
        "Access-Control-Request-Headers": "content-type",
    })
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    response = client.put(f"{SHYMKENT}/draft", content="{", headers={"Content-Type": "application/json"})
    assert check_schema(response, "error", 422)["error"]["details"][0]["reason"] == "json_invalid"


def test_built_frontend_is_served_alongside_api(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<h1>Coyote Supply</h1>", encoding="utf-8")
    with TestClient(create_app(tmp_path / "drafts.sqlite3", frontend_dist=dist)) as client:
        assert "<h1>Coyote Supply</h1>" in client.get("/").text
        assert check_schema(client.get("/api/health"), "health")["status"] == "ok"

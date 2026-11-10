import io
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image

from backend.app import vision_labels
from backend.app.demo_data import load_demo
from backend.app.main import create_app

SHYMKENT = "/api/stores/shymkent-demo"
ALMATY = "/api/stores/almaty-demo"


def test_live_codes_are_isolated_and_idempotent_and_do_not_change_stock(tmp_path):
    db = tmp_path / "live.sqlite3"
    station = str(uuid4())
    payload = {"eventId": str(uuid4()), "stationId": station, "code": "coyote:milk"}
    with TestClient(create_app(db)) as client:
        opening = client.get(SHYMKENT + "/shift").json()
        response = client.post(SHYMKENT + "/vision/live/events", json=payload)
        assert response.status_code == 200, response.text
        first = response.json()
        assert first["storeId"] == "shymkent-demo" and first["ingredientId"] == "milk"
        assert first["source"] == "code" and first["stationId"] == station
        assert client.post(SHYMKENT + "/vision/live/events", json=payload).json() == first
        assert client.post(SHYMKENT + "/vision/live/events", json=payload | {"code": "coyote:oat-milk"}).status_code == 409
        response = client.post(SHYMKENT + "/vision/live/events", json=payload | {
            "eventId": str(uuid4()), "code": "coyote:oat-milk",
        })
        assert response.json()["ingredientId"] == "oat-milk"
        assert client.post(SHYMKENT + "/vision/live/events", json=payload | {
            "eventId": str(uuid4()), "code": "unknown",
        }).status_code == 422
        assert client.get(ALMATY + "/vision/live").json()["events"] == []
        assert client.get(SHYMKENT + "/shift").json() == opening

    with TestClient(create_app(db)) as restarted:
        events = restarted.get(SHYMKENT + "/vision/live").json()["events"]
        assert [event["ingredientId"] for event in events] == ["oat-milk", "milk"]


def jpeg(color):
    target = io.BytesIO()
    Image.new("RGB", (96, 64), color).save(target, "JPEG")
    return target.getvalue()


def test_live_only_journals_two_distinct_matching_labels(tmp_path, monkeypatch):
    labels = iter(("WHOLE MILK", "WHOLE MILK", "OAT DRINK", "WHOLE MILK",
                   "WHOLE MILK", "WHOLE MILK", "COFFEE CREAMER CONTAINS MILK"))
    monkeypatch.setattr(vision_labels, "read_label", lambda frame: next(labels))
    with TestClient(create_app(tmp_path / "live.sqlite3")) as client:
        station = uuid4()
        opening = client.get(SHYMKENT + "/shift").json()

        def analyze(color):
            response = client.post(f"{SHYMKENT}/vision/live/frames/{station}", content=jpeg(color),
                                   headers={"Content-Type": "image/jpeg"})
            assert response.status_code == 200, response.text
            return response.json()

        assert analyze("white")["event"] is None
        assert analyze("white")["event"] is None
        oat = analyze("brown")
        assert oat["ingredientId"] == "oat-milk" and oat["event"] is None
        assert analyze("beige")["event"] is None
        event = analyze("ivory")["event"]
        assert event["source"] == "label" and event["ingredientId"] == "milk"
        assert analyze("tan")["event"] is None
        unknown = analyze("orange")
        assert unknown["ingredientId"] is None and unknown["event"] is None
        assert client.get(SHYMKENT + "/vision/live").json()["events"] == [event]
        assert client.get(SHYMKENT + "/shift").json() == opening


def test_public_live_routes_do_not_expose_imported_store_data(tmp_path):
    dataset = load_demo().model_copy(update={"data_mode": "imported"})
    with TestClient(create_app(tmp_path / "live.sqlite3", dataset=dataset)) as client:
        assert client.get(SHYMKENT + "/vision/live").status_code == 403
        assert client.post(SHYMKENT + "/vision/live/events", json={
            "eventId": str(uuid4()), "stationId": str(uuid4()), "code": "coyote:milk",
        }).status_code == 403

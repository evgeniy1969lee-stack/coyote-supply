import io
from urllib.error import URLError

from fastapi.testclient import TestClient
from PIL import Image

from backend.app import vision
from backend.app.main import create_app

SHIFT = "/api/stores/shymkent-demo/shift"


def frame():
    result = io.BytesIO()
    Image.new("RGB", (96, 64), "white").save(result, "JPEG")
    return result.getvalue()


def analyze(client):
    return client.post(f"{SHIFT}/vision", content=frame(), headers={"Content-Type": "image/jpeg"})


def milk(overview):
    return next(item for item in overview["forecast"]["ingredients"] if item["ingredientId"] == "milk")


def test_vision_proposes_recipe_quantity_and_only_confirmation_changes_stock(tmp_path, monkeypatch):
    monkeypatch.setenv("COYOTE_VISION_URL", "http://127.0.0.1:8082")

    def caption(endpoint, data_url):
        assert endpoint.endswith(":8082")
        assert data_url.startswith("data:image/jpeg;base64,")
        return "A hand is pouring milk from a pitcher into a cup of coffee."

    monkeypatch.setattr(vision, "request_caption", caption)
    db = tmp_path / "shift.sqlite3"
    with TestClient(create_app(db)) as client:
        initial = client.get(SHIFT).json()
        result = analyze(client)
        assert result.status_code == 200, result.text
        proposal = result.json()
        assert proposal["observation"] == "possible_pour"
        assert proposal["ingredientId"] == "milk"
        assert proposal["model"] == "SmolVLM-256M-Instruct"
        portion = next(option for option in proposal["options"] if option["recipeSku"] == "latte-300")
        assert portion["ingredientId"] == "milk" and portion["recipeQty"] == 250
        assert client.get(SHIFT).json() == initial

        confirmation = {
            "eventId": "vision-demo-01", "forecastId": proposal["forecastId"],
            "recipeSku": portion["recipeSku"], "ingredientId": portion["ingredientId"],
            "quantity": portion["recipeQty"],
        }
        mismatched = client.post(f"{SHIFT}/consumptions", json=confirmation | {"recipeSku": "cream-filter"})
        assert mismatched.status_code == 422
        response = client.post(f"{SHIFT}/consumptions", json=confirmation)
        assert response.status_code == 200, response.text
        current = response.json()
        assert milk(current)["onHandQty"] == 19_750
        assert milk(current)["recommendedQty"] == 24_000
        assert milk(current)["daily"][0]["demandQty"] == milk(initial)["daily"][0]["demandQty"] - 250
        assert current["recentLosses"] == []
        event, = current["recentConsumptions"]
        assert event["recipeSku"] == "latte-300"
        assert event["before"]["shortageQty"] == event["after"]["shortageQty"] == 17_000
        assert event["todayDemandBefore"] - event["todayDemandAfter"] == 250
        assert client.post(f"{SHIFT}/consumptions", json=confirmation).json() == current
        assert client.post(f"{SHIFT}/consumptions", json=confirmation | {"eventId": "vision-02"}).status_code == 409
        assert client.post(
            f"{SHIFT}/losses", json={k: v for k, v in confirmation.items() if k != "recipeSku"},
        ).status_code == 422

    with TestClient(create_app(db)) as restarted:
        assert restarted.get(SHIFT).json() == current
        assert restarted.get("/api/stores/almaty-demo/shift").json()["recentConsumptions"] == []


def test_vision_rejects_invalid_frames_and_keeps_ambiguous_images_manual(tmp_path, monkeypatch):
    monkeypatch.setenv("COYOTE_VISION_URL", "http://127.0.0.1:8082")
    with TestClient(create_app(tmp_path / "shift.sqlite3")) as client:
        initial = client.get(SHIFT).json()
        invalid = client.post(f"{SHIFT}/vision", content=b"not an image", headers={"Content-Type": "image/jpeg"})
        assert invalid.status_code == 422
        oversized = client.post(f"{SHIFT}/vision", content=b"x" * 700_000, headers={"Content-Type": "image/jpeg"})
        assert oversized.status_code == 413

        monkeypatch.setattr(vision, "request_caption", lambda *args: "A cup with a spoon. No milk is pouring.")
        ambiguous = analyze(client).json()
        assert ambiguous["observation"] == "unclear" and ambiguous["ingredientId"] is None
        assert ambiguous["options"]

        def offline(*args):
            raise URLError("unavailable")

        monkeypatch.setattr(vision, "request_caption", offline)
        assert analyze(client).status_code == 503
        assert client.get(SHIFT).json() == initial

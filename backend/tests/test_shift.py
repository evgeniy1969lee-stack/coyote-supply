from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from backend.app.main import create_app

SHYMKENT = "/api/stores/shymkent-demo"
ALMATY = "/api/stores/almaty-demo"


def milk(forecast):
    return next(item for item in forecast["ingredients"] if item["ingredientId"] == "milk")


def loss_request(overview, event_id="demo-loss-01", quantity=2000):
    return {
        "eventId": event_id,
        "forecastId": overview["forecast"]["forecastId"],
        "ingredientId": "milk",
        "quantity": quantity,
    }


def test_shift_loss_recalculates_forecast_and_survives_restart(tmp_path):
    db = tmp_path / "shift.sqlite3"
    with TestClient(create_app(db)) as client:
        response = client.get(f"{SHYMKENT}/shift")
        assert response.status_code == 200, response.text
        start = response.json()
        assert start["guardian"]["state"] == "alert"
        assert milk(start["forecast"])["onHandQty"] == 20_000
        assert any(action["id"] == "stockout" for action in start["actions"])
        assert any(action["id"] == "expiry" for action in start["actions"])

        request = loss_request(start)
        posted = client.post(f"{SHYMKENT}/shift/losses", json=request)
        assert posted.status_code == 200, posted.text
        changed = posted.json()
        assert changed["forecast"]["forecastId"] != start["forecast"]["forecastId"]
        assert milk(changed["forecast"])["onHandQty"] == 18_000
        assert milk(changed["forecast"])["recommendedQty"] == 24_000
        assert changed["recentLosses"][0]["before"] == {
            "onHandQty": 20_000, "shortageQty": 17_000, "recommendedQty": 24_000,
        }
        assert changed["recentLosses"][0]["after"] == {
            "onHandQty": 18_000, "shortageQty": 19_000, "recommendedQty": 24_000,
        }
        assert "18" in changed["guardian"]["message"]
        assert client.post(f"{SHYMKENT}/shift/losses", json=request).json() == changed
        conflict = client.post(f"{SHYMKENT}/shift/losses", json=request | {"quantity": 1000})
        assert conflict.status_code == 422
        assert client.get(f"{SHYMKENT}/forecast").json() == changed["forecast"]
        assert client.get(f"{ALMATY}/shift").json()["recentLosses"] == []

    with TestClient(create_app(db)) as restarted:
        assert restarted.get(f"{SHYMKENT}/shift").json() == changed


def test_loss_invalidates_old_draft_version_and_keeps_saved_rows(tmp_path):
    db = tmp_path / "shift.sqlite3"
    with TestClient(create_app(db)) as client:
        before = client.get(f"{SHYMKENT}/shift").json()
        rows = [{"ingredientId": "milk", "quantity": 30_000}]
        draft_request = {"forecastId": before["forecast"]["forecastId"], "rows": rows}
        saved = client.put(f"{SHYMKENT}/draft", json=draft_request).json()["draft"]
        assert saved["totalKzt"] == 21_000
        assert client.get(f"{SHYMKENT}/shift").json()["guardian"]["state"] == "watch"

        after = client.post(f"{SHYMKENT}/shift/losses", json=loss_request(before)).json()
        assert after["draft"] == saved
        assert after["guardian"]["state"] == "alert"
        assert client.put(f"{SHYMKENT}/draft", json=draft_request).status_code == 409
        response = client.put(
            f"{SHYMKENT}/draft",
            json=draft_request | {"forecastId": after["forecast"]["forecastId"]},
        )
        assert response.status_code == 200
        assert response.json()["draft"]["rows"] == saved["rows"]

    with TestClient(create_app(db)) as restarted:
        restored = restarted.get(f"{SHYMKENT}/shift").json()
        assert restored["draft"]["totalKzt"] == 21_000
        assert restored["draft"]["forecastId"] == restored["forecast"]["forecastId"]
        assert milk(restored["forecast"])["onHandQty"] == 18_000


def test_loss_validation_and_concurrent_requests(tmp_path):
    with TestClient(create_app(tmp_path / "shift.sqlite3")) as client:
        before = client.get(f"{SHYMKENT}/shift").json()
        request = loss_request(before)
        for change in (
            {"quantity": 20_001}, {"quantity": 0}, {"quantity": True},
            {"ingredientId": "oat-milk"}, {"ingredientId": "unknown"},
        ):
            result = client.post(f"{SHYMKENT}/shift/losses", json=request | change)
            assert result.status_code == 422
            assert result.json()["error"]["code"] == "invalid_shift"
        assert client.get(f"{SHYMKENT}/shift").json() == before

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(client.post, f"{SHYMKENT}/shift/losses", json=request | {"eventId": key})
                for key in ("event-a", "event-b")
            ]
            assert sorted(future.result().status_code for future in futures) == [200, 409]
        after = client.get(f"{SHYMKENT}/shift").json()
        assert len(after["recentLosses"]) == 1
        assert milk(after["forecast"])["onHandQty"] == 18_000


def test_copilot_uses_current_recipe_stock_and_shift(tmp_path):
    with TestClient(create_app(tmp_path / "shift.sqlite3")) as client:
        def ask(question):
            response = client.post(f"{SHYMKENT}/shift/copilot", json={"question": question})
            assert response.status_code == 200, response.text
            return response.json()

        recipe = ask("Какой состав латте?")
        assert recipe["kind"] == "recipe"
        assert "250 мл" in recipe["answer"] and "18 г" in recipe["answer"]
        assert ask("Сколько молока осталось?")["kind"] == "stock"
        assert "20 л" in ask("Сколько молока осталось?")["answer"]
        assert ask("Что делать первым?")["kind"] == "shift"
        assert ask("Какой курс доллара?")["kind"] == "unsupported"

        before = client.get(f"{SHYMKENT}/shift").json()
        client.post(f"{SHYMKENT}/shift/losses", json=loss_request(before)).raise_for_status()
        assert "18 л" in ask("Сколько молока осталось?")["answer"]
        explained = ask("Что изменилось после списания?")
        assert explained["kind"] == "loss"
        assert "с 20 л до 18 л" in explained["answer"]
        assert "с 17 л до 19 л" in explained["answer"]
        assert "24 л" in explained["answer"] and "страховой запас" in explained["answer"]
        assert client.get("/api/stores/unknown/shift").status_code == 404

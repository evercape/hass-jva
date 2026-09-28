import pytest
from fastapi.testclient import TestClient

from jva_fence.web import STATE, app


@pytest.fixture(autouse=True)
def reset_console():
    STATE.close()
    yield
    STATE.close()


def test_demo_session_reads_zones_and_disarms_one_of_them():
    client = TestClient(app)
    opened = client.post("/api/session", json={"mode": "demo"})
    assert opened.status_code == 200
    body = opened.json()
    assert body["source"] == "demo"
    assert body["page"]["zones"][0]["mode"] == "armed"
    assert body["page"]["zones"][0]["return_voltage_kv"] == 4.2
    assert body["page"]["zones"][0]["voltage_state"] == "ok"

    changed = client.post("/api/zones/1/mode", json={"mode": "disarmed"})
    assert changed.status_code == 200
    zones = {zone["zone_id"]: zone for zone in changed.json()["page"]["zones"]}
    assert zones["1"]["mode"] == "disarmed"
    assert zones["1a"]["mode"] == "armed"

    probe = client.get("/api/investigate")
    assert probe.status_code == 200
    assert probe.json()["api_found"] is False


def test_live_connect_requires_credentials():
    client = TestClient(app)
    response = client.post(
        "/api/session",
        json={"mode": "live", "host": "http://192.168.0.12", "username": "", "password": ""},
    )
    assert response.status_code == 400
    assert "password" in response.json()["detail"]


def test_status_before_connect_is_rejected():
    client = TestClient(app)
    assert client.get("/api/status").status_code == 409

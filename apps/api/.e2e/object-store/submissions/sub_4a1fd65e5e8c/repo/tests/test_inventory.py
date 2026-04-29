from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_create_adjustment():
    response = client.post(
        "/inventory/adjustments",
        json={
            "sku": "sku-123",
            "warehouse_id": "wh-nyc",
            "delta": 5,
            "reason": "cycle count correction",
        },
    )
    assert response.status_code == 200


def test_zero_delta_rejected():
    response = client.post(
        "/inventory/adjustments",
        json={
            "sku": "sku-123",
            "warehouse_id": "wh-nyc",
            "delta": 0,
            "reason": "invalid adjustment",
        },
    )
    assert response.status_code == 400


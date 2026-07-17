from fastapi.testclient import TestClient


def marketing_payload(product_id: int) -> dict[str, object]:
    return {
        "product_id": product_id,
        "audience": "Young professionals",
        "language": "English",
        "platforms": ["TikTok", "Instagram", "Facebook"],
        "tone": "Modern and healthy",
        "objective": "Increase sales",
    }


def test_create_marketing_task(
    client: TestClient, product_payload: dict[str, object]
) -> None:
    product = client.post("/api/v1/products", json=product_payload).json()

    response = client.post(
        "/api/v1/marketing-tasks", json=marketing_payload(product["id"])
    )

    assert response.status_code == 201
    assert response.json()["product_id"] == product["id"]
    assert response.json()["platforms"] == ["TikTok", "Instagram", "Facebook"]


def test_duplicate_platforms_fail(
    client: TestClient, product_payload: dict[str, object]
) -> None:
    product = client.post("/api/v1/products", json=product_payload).json()
    payload = marketing_payload(product["id"])
    payload["platforms"] = ["TikTok", "tiktok"]

    response = client.post("/api/v1/marketing-tasks", json=payload)

    assert response.status_code == 422

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    CopyMatrix,
    MarketingBrief,
    MarketingStrategy,
    VideoProject,
    VideoRenderArtifact,
    VideoRenderTask,
)


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
    assert response.json()["target_markets"] == ["US"]
    assert response.json()["id"] > 0
    assert response.json()["created_at"]


def test_duplicate_platforms_are_deduplicated(
    client: TestClient, product_payload: dict[str, object]
) -> None:
    product = client.post("/api/v1/products", json=product_payload).json()
    payload = marketing_payload(product["id"])
    payload["platforms"] = ["TikTok", "tiktok"]

    response = client.post("/api/v1/marketing-tasks", json=payload)

    assert response.status_code == 201
    assert response.json()["platforms"] == ["TikTok"]


def test_missing_product_fails(client: TestClient) -> None:
    response = client.post("/api/v1/marketing-tasks", json=marketing_payload(999))

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Product not found"


def test_empty_or_unsupported_platforms_fail(
    client: TestClient, product_payload: dict[str, object]
) -> None:
    product = client.post("/api/v1/products", json=product_payload).json()
    empty_payload = marketing_payload(product["id"])
    empty_payload["platforms"] = []
    unsupported_payload = marketing_payload(product["id"])
    unsupported_payload["platforms"] = ["YouTube"]

    assert client.post("/api/v1/marketing-tasks", json=empty_payload).status_code == 422
    assert (
        client.post("/api/v1/marketing-tasks", json=unsupported_payload).status_code
        == 422
    )


def test_product_requires_valid_saved_target_markets(
    client: TestClient, product_payload: dict[str, object]
) -> None:
    product_payload["target_markets"] = []
    product = client.post("/api/v1/products", json=product_payload).json()

    response = client.post(
        "/api/v1/marketing-tasks", json=marketing_payload(product["id"])
    )

    assert response.status_code == 422
    assert "target markets" in response.json()["error"]["message"]


def test_read_one_and_latest_are_isolated_by_product(
    client: TestClient, product_payload: dict[str, object]
) -> None:
    product_a = client.post("/api/v1/products", json=product_payload).json()
    product_payload["name"] = "Second Product"
    product_payload["target_markets"] = ["UK"]
    product_b = client.post("/api/v1/products", json=product_payload).json()

    first = client.post(
        "/api/v1/marketing-tasks", json=marketing_payload(product_a["id"])
    ).json()
    client.patch(
        f"/api/v1/products/{product_a['id']}", json={"target_markets": ["CA"]}
    )
    second_payload = marketing_payload(product_a["id"])
    second_payload["platforms"] = ["Facebook"]
    second = client.post("/api/v1/marketing-tasks", json=second_payload).json()
    client.patch(
        f"/api/v1/products/{product_a['id']}", json={"target_markets": []}
    )

    read_response = client.get(f"/api/v1/marketing-tasks/{first['id']}")
    latest_response = client.get(
        "/api/v1/marketing-tasks/latest", params={"product_id": product_a["id"]}
    )
    empty_response = client.get(
        "/api/v1/marketing-tasks/latest", params={"product_id": product_b["id"]}
    )

    assert read_response.status_code == 200
    assert read_response.json()["id"] == first["id"]
    assert latest_response.status_code == 200
    assert latest_response.json()["id"] == second["id"]
    assert read_response.json()["target_markets"] == ["US"]
    assert latest_response.json()["target_markets"] == ["CA"]
    assert empty_response.status_code == 200
    assert empty_response.json() is None


def test_create_has_no_generated_downstream_side_effects(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    product = client.post("/api/v1/products", json=product_payload).json()

    response = client.post(
        "/api/v1/marketing-tasks", json=marketing_payload(product["id"])
    )

    assert response.status_code == 201
    assert db_session.scalar(select(func.count(MarketingBrief.id))) == 1
    for model in (
        MarketingStrategy,
        CopyMatrix,
        VideoProject,
        VideoRenderTask,
        VideoRenderArtifact,
    ):
        assert db_session.scalar(select(func.count(model.id))) == 0

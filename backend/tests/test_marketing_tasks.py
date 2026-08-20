from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import (
    get_publishing_youtube_provider,
    get_text_generation_provider,
    get_visual_generation_provider,
)
from app.main import app
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


def test_create_marketing_task_supports_complete_four_platform_matrix(
    client: TestClient, product_payload: dict[str, object]
) -> None:
    product = client.post("/api/v1/products", json=product_payload).json()
    payload = marketing_payload(product["id"])
    payload["platforms"] = ["TikTok", "Instagram", "Facebook", "Pinterest"]

    response = client.post("/api/v1/marketing-tasks", json=payload)

    assert response.status_code == 201
    assert response.json()["platforms"] == payload["platforms"]


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
    client.patch(f"/api/v1/products/{product_a['id']}", json={"target_markets": ["CA"]})
    second_payload = marketing_payload(product_a["id"])
    second_payload["platforms"] = ["Facebook"]
    second = client.post("/api/v1/marketing-tasks", json=second_payload).json()
    client.patch(f"/api/v1/products/{product_a['id']}", json={"target_markets": []})

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


def test_product_scoped_candidates_cover_zero_one_and_many_without_side_effects(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    product = client.post("/api/v1/products", json=product_payload).json()
    provider_resolutions = {"qwen": 0, "wanx": 0, "youtube": 0}

    def forbidden_provider(name: str):  # type: ignore[no-untyped-def]
        def resolve():  # type: ignore[no-untyped-def]
            provider_resolutions[name] += 1
            raise AssertionError(f"{name} provider must not be resolved")

        return resolve

    app.dependency_overrides[get_text_generation_provider] = forbidden_provider("qwen")
    app.dependency_overrides[get_visual_generation_provider] = forbidden_provider(
        "wanx"
    )
    app.dependency_overrides[get_publishing_youtube_provider] = forbidden_provider(
        "youtube"
    )

    empty = client.get("/api/v1/marketing-tasks", params={"product_id": product["id"]})
    first = client.post(
        "/api/v1/marketing-tasks", json=marketing_payload(product["id"])
    ).json()
    one = client.get("/api/v1/marketing-tasks", params={"product_id": product["id"]})
    second_payload = marketing_payload(product["id"])
    second_payload["audience"] = "Road trip drivers"
    second_payload["language"] = "French"
    second_payload["platforms"] = ["Facebook"]
    second = client.post("/api/v1/marketing-tasks", json=second_payload).json()
    brief_count_before = db_session.scalar(select(func.count(MarketingBrief.id)))
    many = client.get("/api/v1/marketing-tasks", params={"product_id": product["id"]})
    brief_count_after = db_session.scalar(select(func.count(MarketingBrief.id)))

    assert empty.status_code == 200
    assert empty.json() == []
    assert [item["id"] for item in one.json()] == [first["id"]]
    assert [item["id"] for item in many.json()] == [first["id"], second["id"]]
    assert many.json()[1]["audience"].endswith("Road trip drivers")
    assert many.json()[1]["language"] == "French"
    assert many.json()[1]["platforms"] == ["Facebook"]
    assert many.json()[1]["created_at"]
    assert brief_count_before == brief_count_after == 2
    assert provider_resolutions == {"qwen": 0, "wanx": 0, "youtube": 0}


def test_product_scoped_candidates_reject_missing_product(client: TestClient) -> None:
    response = client.get("/api/v1/marketing-tasks", params={"product_id": 999999})

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Product not found"

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.dependencies import get_text_generation_provider
from app.main import app
from app.models import (
    AdCampaign,
    CopyMatrix,
    MarketingStrategy,
    VideoProject,
)
from app.providers.base import TextGenerationProvider


def create_product(
    client: TestClient,
    product_payload: dict[str, object],
    *,
    name: str = "Feedback Product",
) -> int:
    payload = {**product_payload, "name": name}
    response = client.post("/api/v1/products", json=payload)
    assert response.status_code == 201
    return response.json()["id"]


def add_campaigns(
    db_session: Session,
    product_id: int,
) -> list[AdCampaign]:
    campaigns = [
        AdCampaign(
            product_id=product_id,
            platform="TikTok",
            campaign_name="private-campaign-name-one",
            date=date(2026, 7, 2),
            impressions=100,
            clicks=10,
            conversions=2,
            spend=Decimal("20"),
            revenue=Decimal("60"),
        ),
        AdCampaign(
            product_id=product_id,
            platform="Instagram",
            campaign_name="private-campaign-name-two",
            date=date(2026, 7, 1),
            impressions=900,
            clicks=40,
            conversions=8,
            spend=Decimal("80"),
            revenue=Decimal("240"),
        ),
        AdCampaign(
            product_id=product_id,
            platform="TikTok",
            campaign_name="private-campaign-name-three",
            date=date(2026, 7, 3),
            impressions=0,
            clicks=0,
            conversions=0,
            spend=Decimal("0"),
            revenue=Decimal("0"),
        ),
    ]
    db_session.add_all(campaigns)
    db_session.commit()
    return campaigns


def create_content_chain(
    db_session: Session,
    product_id: int,
    *,
    suffix: str,
) -> tuple[MarketingStrategy, CopyMatrix, VideoProject]:
    strategy = MarketingStrategy(
        product_id=product_id,
        positioning=f"Positioning {suffix}",
        audience_insights=[f"Audience {suffix}"],
        angles=[f"Angle {suffix}"],
        risks=[f"Risk {suffix}"],
        evidence=[f"Evidence {suffix}"],
    )
    db_session.add(strategy)
    db_session.flush()
    copy_matrix = CopyMatrix(
        product_id=product_id,
        marketing_strategy_id=strategy.id,
        copies=[
            {
                "platform": "TikTok",
                "hook": "Hook",
                "caption": "Caption",
                "hashtags": ["#One"],
                "cta": "CTA",
            },
            {
                "platform": "Instagram",
                "hook": "Hook",
                "caption": "Caption",
                "hashtags": ["#Two"],
                "cta": "CTA",
            },
            {
                "platform": "Facebook",
                "hook": "Hook",
                "caption": "Caption",
                "hashtags": ["#Three"],
                "cta": "CTA",
            },
        ],
    )
    db_session.add(copy_matrix)
    db_session.flush()
    project = create_video_project(
        db_session,
        product_id=product_id,
        strategy_id=strategy.id,
        copy_matrix_id=copy_matrix.id,
        suffix=suffix,
    )
    db_session.refresh(strategy)
    db_session.refresh(copy_matrix)
    return strategy, copy_matrix, project


def create_video_project(
    db_session: Session,
    *,
    product_id: int,
    strategy_id: int,
    copy_matrix_id: int,
    suffix: str,
) -> VideoProject:
    project = VideoProject(
        product_id=product_id,
        marketing_strategy_id=strategy_id,
        copy_matrix_id=copy_matrix_id,
        platform="TikTok",
        title=f"Project {suffix}",
        concept="Deterministic concept",
        duration_seconds=10,
        aspect_ratio="9:16",
        scenes=[
            {
                "sequence": 1,
                "duration_seconds": 10,
                "shot_type": "Product",
                "visual_description": "Product scene",
                "action": "Show product",
                "narration": "Narration",
            }
        ],
        cta="Learn more",
        status="planned",
    )
    db_session.add(project)
    db_session.commit()
    db_session.refresh(project)
    return project


def assert_content_chain_failed_closed(body: dict[str, object]) -> None:
    assert body["video_project_id"] is None
    assert body["marketing_strategy_id"] is None
    assert body["copy_matrix_id"] is None
    assert body["content_chain_ready"] is False
    assert body["context_ready"] is False


def feedback_path(product_id: int) -> str:
    return f"/api/v1/products/{product_id}/feedback-context"


def test_feedback_context_missing_product_is_404(
    client: TestClient,
) -> None:
    response = client.get(feedback_path(999))

    assert response.status_code == 404


def test_feedback_context_without_campaigns_is_safe_empty_context(
    client: TestClient,
    product_payload: dict[str, object],
) -> None:
    product_id = create_product(client, product_payload)

    response = client.get(feedback_path(product_id))

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "v1"
    assert body["data_source"] == "stored_campaigns"
    assert body["campaign_ids"] == []
    assert body["campaign_count"] == 0
    assert body["date_from"] is None
    assert body["date_to"] is None
    assert body["platforms"] == []
    assert body["overall_metrics"] is None
    assert body["platform_metrics"] == []
    assert body["metrics_ready"] is False
    assert body["video_project_id"] is None
    assert body["marketing_strategy_id"] is None
    assert body["copy_matrix_id"] is None
    assert body["content_chain_ready"] is False
    assert body["context_ready"] is False
    assert body["missing_requirements"] == [
        "campaign_data",
        "video_project",
    ]
    assert body["provider_calls"] == 0
    assert body["generation_triggered"] is False
    assert len(body["context_digest"]) == 64


def test_feedback_context_aggregates_totals_and_platforms_deterministically(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    product_id = create_product(client, product_payload)
    campaigns = add_campaigns(db_session, product_id)
    strategy, copy_matrix, project = create_content_chain(
        db_session, product_id, suffix="one"
    )

    response = client.get(feedback_path(product_id))

    assert response.status_code == 200
    body = response.json()
    assert body["campaign_ids"] == sorted(item.id for item in campaigns)
    assert body["campaign_count"] == 3
    assert body["date_from"] == "2026-07-01"
    assert body["date_to"] == "2026-07-03"
    assert body["platforms"] == ["Instagram", "TikTok"]
    assert body["overall_metrics"] == {
        "impressions": 1000,
        "clicks": 50,
        "conversions": 10,
        "spend": 100.0,
        "revenue": 300.0,
        "ctr": 0.05,
        "conversion_rate": 0.2,
        "cpa": 10.0,
        "roas": 3.0,
    }
    platform_metrics = {
        item["platform"]: item["metrics"]
        for item in body["platform_metrics"]
    }
    assert platform_metrics["Instagram"]["ctr"] == 0.044444
    assert platform_metrics["TikTok"]["ctr"] == 0.1
    assert body["marketing_strategy_id"] == strategy.id
    assert body["copy_matrix_id"] == copy_matrix.id
    assert body["video_project_id"] == project.id
    assert body["content_chain_ready"] is True
    assert body["context_ready"] is True
    assert body["campaign_association_scope"] == "product_only"
    assert body["creative_attribution_persisted"] is False
    assert body["marketing_brief_attribution_persisted"] is False


def test_feedback_context_zero_division_semantics(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    product_id = create_product(client, product_payload)
    db_session.add(
        AdCampaign(
            product_id=product_id,
            platform="TikTok",
            campaign_name="Zero totals",
            date=date(2026, 7, 1),
            impressions=0,
            clicks=0,
            conversions=0,
            spend=Decimal("0"),
            revenue=Decimal("0"),
        )
    )
    db_session.commit()

    metrics = client.get(feedback_path(product_id)).json()[
        "overall_metrics"
    ]

    assert metrics["ctr"] == 0
    assert metrics["conversion_rate"] == 0
    assert metrics["cpa"] is None
    assert metrics["roas"] is None


def test_feedback_context_uses_latest_video_project_exact_chain_only(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    product_id = create_product(client, product_payload)
    add_campaigns(db_session, product_id)
    strategy, copy_matrix, project = create_content_chain(
        db_session, product_id, suffix="exact"
    )
    unrelated_strategy = MarketingStrategy(
        product_id=product_id,
        positioning="New but unrelated",
        audience_insights=["Audience"],
        angles=["Angle"],
        risks=["Risk"],
        evidence=["Evidence"],
    )
    db_session.add(unrelated_strategy)
    db_session.commit()

    body = client.get(feedback_path(product_id)).json()

    assert body["video_project_id"] == project.id
    assert body["marketing_strategy_id"] == strategy.id
    assert body["copy_matrix_id"] == copy_matrix.id
    assert body["marketing_strategy_id"] != unrelated_strategy.id
    assert body["content_chain_selection"] == (
        "latest_video_project_exact_chain"
    )
    assert body["content_chain_ready"] is True


def test_feedback_context_fails_closed_for_cross_product_copy_chain(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    product_id = create_product(client, product_payload, name="Product A")
    other_product_id = create_product(
        client, product_payload, name="Product B"
    )
    add_campaigns(db_session, product_id)
    strategy, _, _ = create_content_chain(
        db_session, product_id, suffix="valid"
    )
    _, other_copy, _ = create_content_chain(
        db_session, other_product_id, suffix="other"
    )
    invalid_project = create_video_project(
        db_session,
        product_id=product_id,
        strategy_id=strategy.id,
        copy_matrix_id=other_copy.id,
        suffix="cross-copy",
    )

    body = client.get(feedback_path(product_id)).json()
    repeated = client.get(feedback_path(product_id)).json()

    assert_content_chain_failed_closed(body)
    assert body["context_digest"] == repeated["context_digest"]
    assert "exact_content_chain" in body["missing_requirements"]
    assert invalid_project.id not in (
        body["video_project_id"],
        body["marketing_strategy_id"],
        body["copy_matrix_id"],
    )
    assert other_copy.id not in (
        body["video_project_id"],
        body["marketing_strategy_id"],
        body["copy_matrix_id"],
    )

    _, changed_other_copy, _ = create_content_chain(
        db_session, other_product_id, suffix="changed-other"
    )
    invalid_project.copy_matrix_id = changed_other_copy.id
    db_session.commit()

    changed = client.get(feedback_path(product_id)).json()

    assert_content_chain_failed_closed(changed)
    assert changed["context_digest"] != body["context_digest"]


def test_feedback_context_fails_closed_for_cross_product_strategy(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    product_id = create_product(client, product_payload, name="Product A")
    other_product_id = create_product(
        client, product_payload, name="Product B"
    )
    add_campaigns(db_session, product_id)
    _, copy_matrix, _ = create_content_chain(
        db_session, product_id, suffix="local"
    )
    other_strategy, _, _ = create_content_chain(
        db_session, other_product_id, suffix="other"
    )
    invalid_project = create_video_project(
        db_session,
        product_id=product_id,
        strategy_id=other_strategy.id,
        copy_matrix_id=copy_matrix.id,
        suffix="cross-strategy",
    )

    body = client.get(feedback_path(product_id)).json()

    assert_content_chain_failed_closed(body)
    assert "exact_content_chain" in body["missing_requirements"]
    assert other_strategy.id not in (
        body["video_project_id"],
        body["marketing_strategy_id"],
        body["copy_matrix_id"],
    )
    assert invalid_project.id not in (
        body["video_project_id"],
        body["marketing_strategy_id"],
        body["copy_matrix_id"],
    )


def test_feedback_context_fails_closed_for_strategy_reference_mismatch(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    product_id = create_product(client, product_payload)
    add_campaigns(db_session, product_id)
    first_strategy, _, _ = create_content_chain(
        db_session, product_id, suffix="first"
    )
    _, second_copy, _ = create_content_chain(
        db_session, product_id, suffix="second"
    )
    create_video_project(
        db_session,
        product_id=product_id,
        strategy_id=first_strategy.id,
        copy_matrix_id=second_copy.id,
        suffix="mismatch",
    )

    body = client.get(feedback_path(product_id)).json()

    assert_content_chain_failed_closed(body)
    assert "exact_content_chain" in body["missing_requirements"]


@pytest.mark.parametrize(
    ("missing_reference", "missing_requirement"),
    [
        ("marketing_strategy_id", "marketing_strategy"),
        ("copy_matrix_id", "copy_matrix"),
    ],
)
def test_feedback_context_fails_closed_when_chain_record_is_missing(
    missing_reference: str,
    missing_requirement: str,
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    product_id = create_product(client, product_payload)
    add_campaigns(db_session, product_id)
    _, _, project = create_content_chain(
        db_session, product_id, suffix=f"missing-{missing_reference}"
    )
    db_session.execute(
        update(VideoProject)
        .where(VideoProject.id == project.id)
        .values({missing_reference: 999_999})
    )
    db_session.commit()

    body = client.get(feedback_path(product_id)).json()

    assert_content_chain_failed_closed(body)
    assert missing_requirement in body["missing_requirements"]


def test_feedback_context_digest_is_stable_and_tracks_input_changes(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    product_id = create_product(client, product_payload)
    campaigns = add_campaigns(db_session, product_id)
    create_content_chain(db_session, product_id, suffix="first")

    first = client.get(feedback_path(product_id)).json()["context_digest"]
    repeated = client.get(feedback_path(product_id)).json()[
        "context_digest"
    ]
    campaigns[0].clicks += 1
    db_session.commit()
    changed_metric = client.get(feedback_path(product_id)).json()[
        "context_digest"
    ]
    create_content_chain(db_session, product_id, suffix="second")
    changed_chain = client.get(feedback_path(product_id)).json()[
        "context_digest"
    ]

    assert first == repeated
    assert changed_metric != first
    assert changed_chain != changed_metric


def test_feedback_context_is_provider_free_read_only_and_private(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    product_id = create_product(client, product_payload)
    campaigns = add_campaigns(db_session, product_id)
    _, _, project = create_content_chain(
        db_session, product_id, suffix="privacy"
    )
    provider_resolutions = 0

    def forbidden_provider() -> TextGenerationProvider:
        nonlocal provider_resolutions
        provider_resolutions += 1
        raise AssertionError("FeedbackContext resolved a Provider")

    task_counts = {
        model.__name__: int(
            db_session.scalar(select(func.count()).select_from(model)) or 0
        )
        for model in (
            AdCampaign,
            MarketingStrategy,
            CopyMatrix,
            VideoProject,
        )
    }
    campaign_created = [campaign.created_at for campaign in campaigns]
    project_updated = project.updated_at
    app.dependency_overrides[get_text_generation_provider] = forbidden_provider
    try:
        first = client.get(feedback_path(product_id))
        second = client.get(feedback_path(product_id))
    finally:
        app.dependency_overrides.pop(get_text_generation_provider, None)

    assert first.status_code == 200
    assert second.status_code == 200
    assert provider_resolutions == 0
    serialized = first.text.casefold()
    assert "private-campaign-name" not in serialized
    for forbidden in (
        "campaign_name",
        "authorization",
        "api_key",
        "token",
        "prompt",
        "provider_task_id",
        "provider_output",
        "storage_path",
        "c:\\",
    ):
        assert forbidden not in serialized
    assert first.json()["association_notice"]
    assert first.json()["recommendation_generated"] is False
    assert first.json()["generation_triggered"] is False
    for model in (
        AdCampaign,
        MarketingStrategy,
        CopyMatrix,
        VideoProject,
    ):
        assert (
            db_session.scalar(select(func.count()).select_from(model))
            == task_counts[model.__name__]
        )
    for campaign, created_at in zip(campaigns, campaign_created, strict=True):
        db_session.refresh(campaign)
        assert campaign.created_at.replace(tzinfo=None) == created_at.replace(
            tzinfo=None
        )
    db_session.refresh(project)
    assert project.updated_at.replace(tzinfo=None) == project_updated.replace(
        tzinfo=None
    )

from copy import deepcopy
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AdCampaign,
    CopyMatrix,
    GrowthOptimizationExecution,
    GrowthOptimizationRun,
    MarketingStrategy,
    VideoProject,
)
from app.schemas.growth import (
    GrowthAnalysisResponse,
    GrowthRecommendationConstraints,
    compute_recommendation_digest,
)


def _ready_analysis(
    client: TestClient,
    session: Session,
    product_payload: dict[str, object],
) -> GrowthAnalysisResponse:
    product_id = client.post("/api/v1/products", json=product_payload).json()["id"]
    strategy = MarketingStrategy(
        product_id=product_id,
        positioning="Portable routine companion.",
        audience_insights=["Busy shoppers value convenience."],
        angles=["Use it anywhere"],
        risks=["Avoid causal claims."],
        evidence=["USB rechargeable"],
    )
    session.add(strategy)
    session.flush()
    copy_matrix = CopyMatrix(
        product_id=product_id,
        marketing_strategy_id=strategy.id,
        copies=[
            {
                "platform": platform,
                "hook": "Hook",
                "caption": "Caption",
                "hashtags": ["#Safe"],
                "cta": "CTA",
            }
            for platform in ("TikTok", "Instagram", "Facebook", "Pinterest")
        ],
    )
    session.add(copy_matrix)
    session.flush()
    project = VideoProject(
        product_id=product_id,
        marketing_strategy_id=strategy.id,
        copy_matrix_id=copy_matrix.id,
        platform="TikTok",
        title="Portable routine",
        concept="Show one controlled use case.",
        duration_seconds=10,
        aspect_ratio="9:16",
        scenes=[
            {
                "sequence": 1,
                "duration_seconds": 10,
                "shot_type": "Product",
                "visual_description": "Portable blender",
                "action": "Blend a drink",
                "narration": "Blend anywhere",
            }
        ],
        cta="Learn more",
        status="planned",
    )
    session.add(project)
    for platform, revenue in (
        ("TikTok", "500"),
        ("Instagram", "200"),
        ("Pinterest", "50"),
    ):
        session.add(
            AdCampaign(
                product_id=product_id,
                platform=platform,
                campaign_name=f"{platform} campaign",
                date=date(2026, 8, 20),
                impressions=1000,
                clicks=50,
                conversions=10,
                spend=Decimal("100"),
                revenue=Decimal(revenue),
            )
        )
    session.commit()
    digest = client.get(f"/api/v1/products/{product_id}/feedback-context").json()[
        "context_digest"
    ]
    recommendation = GrowthRecommendationConstraints.model_validate(
        {
            "summary": "Rebalance a controlled test using observed ROAS.",
            "observations": [
                {
                    "scope": "platform",
                    "platform": "Pinterest",
                    "metric": "roas",
                    "direction": "investigate",
                    "hypothesis": "Test a lower allocation while refreshing creative.",
                }
            ],
            "copy_constraints": [
                {
                    "platform": platform,
                    "hook_direction": "Keep product use clear.",
                    "message_angle": "Show practical value.",
                    "cta_direction": "Invite a controlled test.",
                    "must_preserve": ["Product identity"],
                    "must_avoid": ["Guaranteed outcomes"],
                }
                for platform in ("TikTok", "Instagram", "Facebook", "Pinterest")
            ],
            "video_constraint": {
                "platform": "TikTok",
                "opening_hook_direction": "Show the product immediately.",
                "visual_focus": "The exact product.",
                "pacing_direction": "Keep the opening concise.",
                "cta_direction": "Invite viewers to learn more.",
                "must_preserve": ["Product visibility"],
                "must_avoid": ["Guaranteed outcomes"],
            },
            "budget_guidance": "Shift budget gradually toward stronger ROAS.",
        }
    )
    recommendation_digest = compute_recommendation_digest(
        product_id=product_id,
        source_context_digest=digest,
        source_marketing_strategy_id=strategy.id,
        source_copy_matrix_id=copy_matrix.id,
        source_video_project_id=project.id,
        recommendation=recommendation,
    )
    return GrowthAnalysisResponse(
        product_id=product_id,
        source_context_digest=digest,
        source_marketing_strategy_id=strategy.id,
        source_copy_matrix_id=copy_matrix.id,
        source_video_project_id=project.id,
        recommendation=recommendation,
        recommendation_digest=recommendation_digest,
    )


def _request(analysis: GrowthAnalysisResponse) -> dict[str, object]:
    return {
        "analysis": analysis.model_dump(mode="json"),
        "policy": {
            "total_budget": 300,
            "target_roas": 2,
            "minimum_platform_share": 0.1,
            "performance_tilt_share": 0.15,
            "maximum_bid_adjustment_pct": 0.2,
        },
    }


def test_plan_rebalances_budget_and_bids_without_provider_or_write(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    analysis = _ready_analysis(client, db_session, product_payload)
    before = int(db_session.scalar(select(func.count()).select_from(AdCampaign)) or 0)

    response = client.post(
        f"/api/v1/products/{analysis.product_id}/growth-optimization/plan",
        json=_request(analysis),
    )

    assert response.status_code == 200
    body = response.json()
    actions = {item["platform"]: item for item in body["actions"]}
    assert set(actions) == {"Instagram", "Pinterest", "TikTok"}
    assert sum(item["recommended_budget"] for item in actions.values()) == 300
    assert actions["TikTok"]["recommended_budget"] > 100
    assert actions["Pinterest"]["recommended_budget"] < 100
    assert actions["TikTok"]["action"] == "increase"
    assert actions["Instagram"]["action"] == "hold"
    assert actions["Pinterest"]["action"] == "decrease"
    assert body["requires_qwen_recommendation"] is True
    assert body["automatic_plan_generated"] is True
    assert body["simulation_only"] is True
    assert body["external_execution_allowed"] is False
    assert body["provider_calls"] == 0
    assert (
        int(db_session.scalar(select(func.count()).select_from(AdCampaign)) or 0)
        == before
    )


def test_plan_rejects_tampered_recommendation_and_stale_context(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    analysis = _ready_analysis(client, db_session, product_payload)
    request = _request(analysis)
    tampered = deepcopy(request)
    tampered["analysis"]["recommendation"]["budget_guidance"] = "Spend everything."
    path = f"/api/v1/products/{analysis.product_id}/growth-optimization/plan"

    assert client.post(path, json=tampered).status_code == 409

    db_session.add(
        AdCampaign(
            product_id=analysis.product_id,
            platform="Facebook",
            campaign_name="New data",
            date=date(2026, 8, 20),
            impressions=10,
            clicks=1,
            conversions=0,
            spend=Decimal("10"),
            revenue=Decimal("0"),
        )
    )
    db_session.commit()
    stale = client.post(path, json=request)
    assert stale.status_code == 409
    assert stale.json()["error"]["message"] == (
        "FeedbackContext changed; generate a new analysis first"
    )


def test_persisted_plans_are_idempotent_versioned_and_internally_activated(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    analysis = _ready_analysis(client, db_session, product_payload)
    path = f"/api/v1/products/{analysis.product_id}/growth-optimization/plans"
    first_request = {
        **_request(analysis),
        "idempotency_key": "growth-plan-one",
        "activate_internal": True,
    }

    first = client.post(path, json=first_request)
    repeated = client.post(path, json=first_request)

    assert first.status_code == 200
    assert repeated.status_code == 200
    assert first.json()["reused"] is False
    assert repeated.json()["reused"] is True
    assert first.json()["run"]["status"] == "ACTIVE"
    assert first.json()["automatic_internal_application"] is True
    assert first.json()["run"]["external_execution_status"] == "NOT_CONNECTED"
    assert repeated.json()["run"]["id"] == first.json()["run"]["id"]
    assert (
        db_session.scalar(select(func.count()).select_from(GrowthOptimizationRun)) == 1
    )

    second_request = {
        **_request(analysis),
        "idempotency_key": "growth-plan-two",
        "activate_internal": False,
    }
    second = client.post(path, json=second_request)
    assert second.status_code == 200
    assert second.json()["run"]["status"] == "PROPOSED"

    activated = client.post(f"{path}/{second.json()['run']['id']}/activate")
    assert activated.status_code == 200
    assert activated.json()["run"]["status"] == "ACTIVE"
    assert activated.json()["external_execution_allowed"] is False
    listed = client.get(path)
    assert listed.status_code == 200
    assert [item["status"] for item in listed.json()] == [
        "SUPERSEDED",
        "ACTIVE",
    ]


def test_persisted_plan_rejects_key_conflict_and_stale_activation(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    analysis = _ready_analysis(client, db_session, product_payload)
    path = f"/api/v1/products/{analysis.product_id}/growth-optimization/plans"
    request = {
        **_request(analysis),
        "idempotency_key": "growth-plan-conflict",
        "activate_internal": False,
    }
    created = client.post(path, json=request)
    assert created.status_code == 200

    changed = deepcopy(request)
    changed["policy"]["total_budget"] = 500
    assert client.post(path, json=changed).status_code == 409

    db_session.add(
        AdCampaign(
            product_id=analysis.product_id,
            platform="Facebook",
            campaign_name="Changed context",
            date=date(2026, 8, 20),
            impressions=100,
            clicks=5,
            conversions=1,
            spend=Decimal("20"),
            revenue=Decimal("20"),
        )
    )
    db_session.commit()
    activate = client.post(f"{path}/{created.json()['run']['id']}/activate")
    assert activate.status_code == 409
    assert activate.json()["error"]["message"] == (
        "FeedbackContext changed; create a new optimization plan"
    )


def test_active_plan_sandbox_execution_is_confirmed_idempotent_and_rollbackable(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    analysis = _ready_analysis(client, db_session, product_payload)
    plans_path = f"/api/v1/products/{analysis.product_id}/growth-optimization/plans"
    created = client.post(
        plans_path,
        json={
            **_request(analysis),
            "idempotency_key": "growth-sandbox-plan",
            "activate_internal": True,
        },
    )
    run = created.json()["run"]
    execution_path = f"{plans_path}/{run['id']}/sandbox-executions"
    before_count = int(
        db_session.scalar(select(func.count()).select_from(GrowthOptimizationExecution))
        or 0
    )

    preflight = client.get(f"{plans_path}/{run['id']}/execution-preflight")
    assert preflight.status_code == 200
    assert preflight.json() == {
        "product_id": analysis.product_id,
        "optimization_run_id": run["id"],
        "source_context_digest": analysis.source_context_digest,
        "ready": True,
        "execution_mode": "SANDBOX",
        "provider_name": "sandbox_ad_adapter",
        "requires_explicit_confirmation": True,
        "external_mutation_allowed": False,
        "provider_calls": 0,
        "database_writes": 0,
    }
    assert (
        int(
            db_session.scalar(
                select(func.count()).select_from(GrowthOptimizationExecution)
            )
            or 0
        )
        == before_count
    )
    assert (
        client.post(
            execution_path,
            json={
                "idempotency_key": "growth-sandbox-execution",
                "expected_context_digest": analysis.source_context_digest,
                "confirm_sandbox_execution": False,
            },
        ).status_code
        == 422
    )

    request = {
        "idempotency_key": "growth-sandbox-execution",
        "expected_context_digest": analysis.source_context_digest,
        "confirm_sandbox_execution": True,
    }
    first = client.post(execution_path, json=request)
    repeated = client.post(execution_path, json=request)
    assert first.status_code == 200
    assert repeated.status_code == 200
    assert first.json()["reused"] is False
    assert repeated.json()["reused"] is True
    assert repeated.json()["execution"]["id"] == first.json()["execution"]["id"]
    execution = first.json()["execution"]
    assert execution["status"] == "SUCCEEDED"
    assert execution["execution_mode"] == "SANDBOX"
    assert execution["provider_name"] == "sandbox_ad_adapter"
    assert execution["external_mutation_performed"] is False
    assert first.json()["provider_calls"] == 0
    assert all(item["action"] == "hold" for item in execution["before_actions"])
    assert execution["result_actions"] == execution["target_actions"]
    assert (
        db_session.scalar(select(func.count()).select_from(GrowthOptimizationExecution))
        == 1
    )

    listed = client.get(
        f"/api/v1/products/{analysis.product_id}/growth-optimization/executions"
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [execution["id"]]

    rollback_path = (
        f"/api/v1/products/{analysis.product_id}/growth-optimization/"
        f"executions/{execution['id']}/rollback"
    )
    rolled_back = client.post(rollback_path)
    repeated_rollback = client.post(rollback_path)
    assert rolled_back.status_code == 200
    assert rolled_back.json()["reused"] is False
    assert repeated_rollback.json()["reused"] is True
    restored = rolled_back.json()["execution"]
    assert restored["status"] == "ROLLED_BACK"
    assert restored["result_actions"] == restored["before_actions"]
    assert restored["rolled_back_at"] is not None
    assert rolled_back.json()["external_mutation_performed"] is False


def test_sandbox_execution_rejects_proposed_stale_and_key_conflict(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    analysis = _ready_analysis(client, db_session, product_payload)
    plans_path = f"/api/v1/products/{analysis.product_id}/growth-optimization/plans"
    proposed = client.post(
        plans_path,
        json={
            **_request(analysis),
            "idempotency_key": "growth-proposed-plan",
            "activate_internal": False,
        },
    ).json()["run"]
    assert (
        client.get(f"{plans_path}/{proposed['id']}/execution-preflight").status_code
        == 409
    )

    active = client.post(f"{plans_path}/{proposed['id']}/activate").json()["run"]
    execution_path = f"{plans_path}/{active['id']}/sandbox-executions"
    request = {
        "idempotency_key": "growth-conflict-execution",
        "expected_context_digest": analysis.source_context_digest,
        "confirm_sandbox_execution": True,
    }
    assert client.post(execution_path, json=request).status_code == 200
    conflicting = {**request, "expected_context_digest": "0" * 64}
    assert client.post(execution_path, json=conflicting).status_code == 409

    db_session.add(
        AdCampaign(
            product_id=analysis.product_id,
            platform="Facebook",
            campaign_name="Stale sandbox context",
            date=date(2026, 8, 21),
            impressions=10,
            clicks=1,
            conversions=0,
            spend=Decimal("5"),
            revenue=Decimal("0"),
        )
    )
    db_session.commit()
    assert (
        client.get(f"{plans_path}/{active['id']}/execution-preflight").status_code
        == 409
    )

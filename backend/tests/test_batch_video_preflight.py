from decimal import Decimal

import pytest

from app.models import (
    BatchVideoJob,
    BatchVideoVariant,
    BrandKit,
    BrandKitVersion,
    ExecutionJob,
    Product,
)
from app.schemas.batch_video import BatchVideoRequest
from app.services.batch_video_preflight import BatchVideoPreflightService


def _product(session, name: str, *, brand: BrandKitVersion | None = None) -> Product:
    product = Product(
        name=name,
        category="Test",
        description="Provider-free batch test product",
        selling_points=["Stable"],
        target_markets=["CN"],
        brand_kit_version_id=brand.id if brand else None,
    )
    session.add(product)
    session.commit()
    return product


def _request(ids: list[int], **overrides: object) -> BatchVideoRequest:
    values: dict[str, object] = {
        "product_ids": ids,
        "platforms": ["youtube", "tiktok", "instagram"],
        "variants_per_platform": 2,
        "duration_seconds": 15,
        "aspect_ratio": "9:16",
        "language": "zh-CN",
        "priority": 50,
        "max_concurrency": 3,
        "creative_angle": None,
        "idempotency_key": "batch-preflight-test",
    }
    values.update(overrides)
    return BatchVideoRequest.model_validate(values)


def test_preflight_expands_three_by_three_by_two_without_writes(db_session) -> None:
    products = [_product(db_session, f"Product {index}") for index in range(3)]
    before = set(db_session.new), set(db_session.dirty), set(db_session.deleted)
    result = BatchVideoPreflightService(db_session).run(
        _request([product.id for product in reversed(products)])
    )
    after = set(db_session.new), set(db_session.dirty), set(db_session.deleted)

    assert result.ready is True
    assert result.variant_count == 18
    assert [
        (v.product_id, v.platform, v.variant_index) for v in result.variants
    ] == sorted(
        (product.id, platform, index)
        for product in products
        for platform in ("instagram", "tiktok", "youtube")
        for index in (1, 2)
    )
    assert result.current_stage_cost == Decimal("0")
    assert result.cost_scope == "orchestration_only"
    assert result.downstream_provider_cost_status == "NOT_ESTIMATED"
    assert result.provider_call_count == result.ffmpeg_call_count == 0
    assert before == after


def test_preflight_freezes_exact_brand_version_and_digest(db_session) -> None:
    kit = BrandKit(name="Frozen brand")
    db_session.add(kit)
    db_session.flush()
    version = BrandKitVersion(
        brand_kit_id=kit.id,
        version_number=1,
        digest="a" * 64,
        brand_name="Frozen",
        positioning="Stable",
        default_language="zh-CN",
        brand_tone="Clear",
        preferred_terms=[],
        forbidden_terms=[],
        target_regions=[],
        audience_guidelines=[],
        visual_guidelines=[],
        required_disclosures=[],
        claims_constraints=[],
    )
    db_session.add(version)
    db_session.commit()
    product = _product(db_session, "Branded", brand=version)

    result = BatchVideoPreflightService(db_session).run(
        _request(
            [product.id],
            platforms=["youtube"],
            variants_per_platform=1,
            max_concurrency=1,
        )
    )
    assert result.variants[0].brand_kit_version_id == version.id
    assert result.variants[0].brand_kit_version_digest == "a" * 64


@pytest.mark.parametrize(
    ("case", "overrides", "expected_status"),
    [
        ("duplicate products", {"product_ids": [1, 1]}, 422),
        ("duplicate platforms", {"platforms": ["youtube", "youtube"]}, 422),
        ("missing product", {"product_ids": [999]}, 404),
        ("pinterest", {"platforms": ["pinterest"]}, 422),
        ("invalid platform", {"platforms": ["facebook"]}, 422),
        ("zero variants", {"variants_per_platform": 0}, 422),
        ("too many variants", {"variants_per_platform": 11}, 422),
        (
            "total quota",
            {"variants_per_platform": 10, "product_ids": list(range(1, 21))},
            422,
        ),
        ("zero concurrency", {"max_concurrency": 0}, 422),
        ("concurrency schema limit", {"max_concurrency": 21}, 422),
        (
            "concurrency exceeds expansion",
            {
                "platforms": ["youtube"],
                "variants_per_platform": 1,
                "max_concurrency": 2,
            },
            422,
        ),
        ("invalid duration", {"duration_seconds": 30}, 422),
        ("invalid aspect", {"aspect_ratio": "16:9"}, 422),
        ("invalid language", {"language": "not valid"}, 422),
    ],
)
def test_invalid_preflight_is_rejected_without_batch_writes(
    client, db_session, case, overrides, expected_status
) -> None:
    del case
    _product(db_session, "Only product")
    payload = _request([1]).model_dump(mode="json")
    payload.update(overrides)
    response = client.post("/api/v1/batch-video-jobs/preflight", json=payload)
    assert response.status_code == expected_status
    assert db_session.query(BatchVideoJob).count() == 0
    assert db_session.query(BatchVideoVariant).count() == 0
    assert db_session.query(ExecutionJob).count() == 0


def test_product_with_missing_brand_version_is_rejected_without_writes(
    client, db_session
) -> None:
    product = _product(db_session, "Broken brand binding")
    db_session.execute(
        __import__("sqlalchemy").text(
            "UPDATE products SET brand_kit_version_id = 999999 WHERE id = :id"
        ),
        {"id": product.id},
    )
    db_session.commit()
    db_session.expire_all()
    response = client.post(
        "/api/v1/batch-video-jobs/preflight",
        json=_request(
            [product.id],
            platforms=["youtube"],
            variants_per_platform=1,
            max_concurrency=1,
        ).model_dump(mode="json"),
    )
    assert response.status_code == 409
    assert db_session.query(BatchVideoJob).count() == 0
    assert db_session.query(BatchVideoVariant).count() == 0
    assert db_session.query(ExecutionJob).count() == 0

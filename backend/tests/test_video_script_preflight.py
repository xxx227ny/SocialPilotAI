from decimal import Decimal

import pytest

from app.core.exceptions import AppError
from app.models import (
    BatchVideoJob,
    BatchVideoVariant,
    BrandKit,
    BrandKitVersion,
    Product,
    VideoScriptVersion,
    VideoStoryboardSceneVersion,
)
from app.schemas.video_script_version import VideoScriptDraftRequest
from app.services.video_script_preflight import VideoScriptPreflightService


def script_state(session, variant_id: int) -> tuple[object, ...]:
    session.expire_all()
    variant = session.get(BatchVideoVariant, variant_id)
    assert variant is not None
    return (
        session.query(VideoScriptVersion).count(),
        session.query(VideoStoryboardSceneVersion).count(),
        variant.script_version_sequence,
        variant.active_script_version_id,
        len(session.new),
        len(session.dirty),
        len(session.deleted),
    )


def ready_variant(session, *, forbidden: list[str] | None = None) -> BatchVideoVariant:
    suffix = session.query(Product).count() + 1
    kit = BrandKit(name="Script brand")
    session.add(kit)
    session.flush()
    brand = BrandKitVersion(
        brand_kit_id=kit.id,
        version_number=1,
        digest="a" * 64,
        brand_name="Exact",
        positioning="Stable",
        default_language="zh-CN",
        brand_tone="Clear",
        preferred_terms=[],
        forbidden_terms=forbidden or [],
        target_regions=[],
        audience_guidelines=[],
        visual_guidelines=[],
        required_disclosures=[],
        claims_constraints=[],
    )
    session.add(brand)
    session.flush()
    product = Product(
        name="Product",
        category="Test",
        description="Stable",
        selling_points=["One"],
        target_markets=["CN"],
        brand_kit_version_id=brand.id,
    )
    session.add(product)
    session.flush()
    batch = BatchVideoJob(
        request_digest=f"{suffix:064x}",
        idempotency_key=f"script-batch-{suffix}",
        status="READY_FOR_SCRIPT",
        priority=50,
        variant_count=1,
        max_concurrency=1,
        current_stage_cost=0,
        currency="USD",
        cost_scope="orchestration_only",
        downstream_provider_cost_status="NOT_ESTIMATED",
        cost_confirmed=True,
        frozen_constraints_json={},
    )
    session.add(batch)
    session.flush()
    variant = BatchVideoVariant(
        batch_video_job_id=batch.id,
        product_id=product.id,
        platform="youtube",
        variant_index=1,
        duration_seconds=15,
        aspect_ratio="9:16",
        language="zh-CN",
        creative_angle="proof",
        brand_kit_version_id=brand.id,
        brand_kit_version_digest=brand.digest,
        source_digest=f"{suffix + 100:064x}",
        idempotency_key=f"script-variant-{suffix}",
        status="READY_FOR_SCRIPT",
        result_entity_type="BatchVideoVariant",
        result_entity_id=suffix,
    )
    session.add(variant)
    session.commit()
    return variant


def draft(**overrides: object) -> VideoScriptDraftRequest:
    value: dict[str, object] = {
        "source_type": "MANUAL",
        "idempotency_key": "script-version-1",
        "title": "Title",
        "concept": "Concept",
        "hook": "Hook",
        "cta": "CTA",
        "scenes": [
            {
                "sequence": 1,
                "start_ms": 0,
                "end_ms": 5000,
                "shot_type": "wide",
                "visual_description": "Visual one",
                "action_description": "Move",
                "narration": "Narration one",
                "subtitle_draft": "Subtitle one",
            },
            {
                "sequence": 2,
                "start_ms": 5000,
                "end_ms": 15000,
                "shot_type": "close",
                "visual_description": "Visual two",
                "action_description": "",
                "narration": "Narration two",
                "subtitle_draft": "Subtitle two",
            },
        ],
    }
    value.update(overrides)
    return VideoScriptDraftRequest.model_validate(value)


def test_preflight_derives_authoritative_text_and_writes_nothing(db_session) -> None:
    variant = ready_variant(db_session)
    before = script_state(db_session, variant.id)
    result = VideoScriptPreflightService(db_session).run(variant.id, draft())
    assert script_state(db_session, variant.id) == before
    assert result.full_narration == "Narration one Narration two"
    assert result.full_subtitle_draft == "Subtitle one Subtitle two"
    assert result.current_stage_cost == Decimal("0")
    assert result.cost_scope == "manual_versioning_only"
    assert result.provider_call_count == result.database_writes == 0
    assert result.review_status == "UNREVIEWED"


@pytest.mark.parametrize(
    "scenes",
    [
        [
            {
                "sequence": 1,
                "start_ms": 1,
                "end_ms": 15000,
                "shot_type": "x",
                "visual_description": "x",
                "action_description": "",
                "narration": "x",
                "subtitle_draft": "x",
            }
        ],
        [
            {
                "sequence": 1,
                "start_ms": 0,
                "end_ms": 14000,
                "shot_type": "x",
                "visual_description": "x",
                "action_description": "",
                "narration": "x",
                "subtitle_draft": "x",
            }
        ],
    ],
)
def test_invalid_timeline_is_zero_write(db_session, scenes) -> None:
    variant = ready_variant(db_session)
    with pytest.raises(AppError):
        VideoScriptPreflightService(db_session).run(variant.id, draft(scenes=scenes))
    assert variant.script_version_sequence == 0


def test_brand_forbidden_word_is_deterministic(db_session) -> None:
    variant = ready_variant(db_session, forbidden=["blocked phrase"])
    with pytest.raises(AppError) as failure:
        VideoScriptPreflightService(db_session).run(
            variant.id, draft(concept="Contains blocked phrase")
        )
    assert failure.value.status_code == 422


@pytest.mark.parametrize(
    "status",
    ["WAITING", "RUNNING", "PAUSED", "FAILED", "CANCELLED"],
)
def test_every_real_non_ready_variant_status_is_four_way_zero_write(
    db_session, status
) -> None:
    variant = ready_variant(db_session)
    variant.status = status
    variant.result_entity_type = None
    variant.result_entity_id = None
    db_session.commit()
    before = script_state(db_session, variant.id)
    with pytest.raises(AppError) as failure:
        VideoScriptPreflightService(db_session).run(variant.id, draft())
    assert failure.value.status_code == 409
    assert script_state(db_session, variant.id) == before


def _valid_payload() -> dict[str, object]:
    return draft().model_dump(mode="json")


@pytest.mark.parametrize(
    ("case", "mutate"),
    [
        ("zero scenes", lambda value: value.update(scenes=[])),
        (
            "over twelve scenes",
            lambda value: value.update(
                scenes=[
                    {
                        "sequence": index,
                        "start_ms": index - 1,
                        "end_ms": index,
                        "shot_type": "x",
                        "visual_description": "x",
                        "action_description": "",
                        "narration": "x",
                        "subtitle_draft": "x",
                    }
                    for index in range(1, 14)
                ]
            ),
        ),
        ("sequence starts at two", lambda value: value["scenes"][0].update(sequence=2)),
        ("sequence gap", lambda value: value["scenes"][1].update(sequence=3)),
        ("sequence duplicate", lambda value: value["scenes"][1].update(sequence=1)),
        ("first starts late", lambda value: value["scenes"][0].update(start_ms=1)),
        ("timeline gap", lambda value: value["scenes"][1].update(start_ms=5001)),
        ("timeline overlap", lambda value: value["scenes"][1].update(start_ms=4999)),
        (
            "non-positive scene",
            lambda value: value["scenes"][0].update(start_ms=5000, end_ms=5000),
        ),
        ("ends early", lambda value: value["scenes"][1].update(end_ms=14999)),
        ("empty title", lambda value: value.update(title=" ")),
        ("empty concept", lambda value: value.update(concept=" ")),
        ("empty hook", lambda value: value.update(hook=" ")),
        ("empty cta", lambda value: value.update(cta=" ")),
        (
            "empty visual",
            lambda value: value["scenes"][0].update(visual_description=" "),
        ),
        ("empty narration", lambda value: value["scenes"][0].update(narration=" ")),
        (
            "empty subtitle",
            lambda value: value["scenes"][0].update(subtitle_draft=" "),
        ),
        ("override platform", lambda value: value.update(platform="tiktok")),
        ("override language", lambda value: value.update(language="en-US")),
        ("override angle", lambda value: value.update(creative_angle="override")),
        (
            "override narration",
            lambda value: value.update(full_narration="conflict"),
        ),
        (
            "override subtitles",
            lambda value: value.update(full_subtitle_draft="conflict"),
        ),
    ],
)
def test_every_invalid_structure_is_four_way_zero_write(
    client, db_session, case, mutate
) -> None:
    del case
    variant = ready_variant(db_session)
    payload = _valid_payload()
    mutate(payload)
    before = script_state(db_session, variant.id)
    response = client.post(
        f"/api/v1/batch-video-variants/{variant.id}/script-versions/preflight",
        json=payload,
    )
    assert response.status_code in {409, 422}
    assert script_state(db_session, variant.id) == before


def test_qwen_generated_is_rejected_by_http_with_four_way_zero_write(
    client, db_session
) -> None:
    variant = ready_variant(db_session)
    payload = _valid_payload()
    payload["source_type"] = "QWEN_GENERATED"
    before = script_state(db_session, variant.id)
    response = client.post(
        f"/api/v1/batch-video-variants/{variant.id}/script-versions/preflight",
        json=payload,
    )
    assert response.status_code == 422
    assert script_state(db_session, variant.id) == before

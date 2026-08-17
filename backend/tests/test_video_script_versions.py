import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.exceptions import AppError
from app.db.base import Base
from app.models import (
    BatchVideoVariant,
    BrandKit,
    BrandKitVersion,
    CopyMatrix,
    MarketingStrategy,
    Product,
    VideoProject,
    VideoScriptVersion,
    VideoStoryboardSceneVersion,
)
from app.providers.instagram_provider import InstagramProvider
from app.providers.qwen_provider import QwenProvider
from app.providers.tiktok_provider import TikTokProvider
from app.providers.wanx_provider import WanxProvider
from app.providers.youtube_provider import YouTubeProvider
from app.schemas.video_script_version import VideoScriptCreateRequest
from app.services.video_script_preflight import VideoScriptPreflightService
from app.services.video_script_version_service import VideoScriptVersionService
from tests.test_video_script_preflight import draft, ready_variant, script_state


def request_from_preflight(value, checked, **overrides) -> VideoScriptCreateRequest:
    payload = {
        **value.model_dump(),
        "source_digest": checked.source_digest,
        "content_digest": checked.content_digest,
        "preflight_digest": checked.preflight_digest,
        "preflight_expires_at": checked.expires_at,
    }
    payload.update(overrides)
    return VideoScriptCreateRequest.model_validate(payload)


def create_request(
    session,
    variant_id: int,
    *,
    key: str,
    title: str = "Title",
    parent: int | None = None,
) -> VideoScriptCreateRequest:
    value = draft(idempotency_key=key, title=title, parent_version_id=parent)
    checked = VideoScriptPreflightService(session).run(variant_id, value)
    return request_from_preflight(value, checked)


def test_immutable_versions_idempotency_parent_and_activation(db_session) -> None:
    variant = ready_variant(db_session)
    service = VideoScriptVersionService(db_session)
    first_request = create_request(db_session, variant.id, key="script-key-v1")
    first = service.create(variant.id, first_request)
    first_snapshot = first.version.model_dump(exclude={"created_at"})
    assert first.reused is False and first.version.version_number == 1
    assert first.version.parent_version_id is None
    after_first = script_state(db_session, variant.id)
    reused = service.create(variant.id, first_request)
    assert reused.reused is True and reused.version.id == first.version.id
    assert script_state(db_session, variant.id) == after_first
    with pytest.raises(AppError) as conflict:
        service.create(
            variant.id,
            create_request(
                db_session, variant.id, key="script-key-v1", title="Changed"
            ),
        )
    assert conflict.value.status_code == 409
    assert script_state(db_session, variant.id) == after_first
    second = service.create(
        variant.id,
        create_request(
            db_session,
            variant.id,
            key="script-key-v2",
            title="Changed",
            parent=first.version.id,
        ),
    )
    third = service.create(
        variant.id,
        create_request(
            db_session,
            variant.id,
            key="script-key-v3",
            title="Changed",
            parent=second.version.id,
        ),
    )
    assert [item.version_number for item in service.list(variant.id)] == [1, 2, 3]
    assert second.version.parent_version_id == first.version.id
    assert first_snapshot == service.get(variant.id, first.version.id).model_dump(
        exclude={"created_at"}
    )
    assert service.activate(variant.id, first.version.id).reused is False
    assert service.activate(variant.id, first.version.id).reused is True
    assert (
        service.activate(variant.id, second.version.id).active_script_version_id
        == second.version.id
    )
    assert third.version.content_digest == second.version.content_digest
    before_fourth = script_state(db_session, variant.id)
    fourth = service.create(
        variant.id,
        create_request(
            db_session,
            variant.id,
            key="script-key-v4",
            title="Changed",
            parent=third.version.id,
        ),
    )
    after_fourth = script_state(db_session, variant.id)
    assert fourth.version.content_digest == third.version.content_digest
    assert fourth.version.id != third.version.id
    assert fourth.version.version_number == third.version.version_number + 1
    assert after_fourth[:4] == (
        before_fourth[0] + 1,
        before_fourth[1] + len(fourth.version.scenes),
        before_fourth[2] + 1,
        before_fourth[3],
    )


def test_orm_rejects_update_and_delete(db_session) -> None:
    variant = ready_variant(db_session)
    created = VideoScriptVersionService(db_session).create(
        variant.id, create_request(db_session, variant.id, key="immutable-key")
    )
    version = db_session.get(VideoScriptVersion, created.version.id)
    assert version is not None
    version.title = "mutated"
    with pytest.raises(ValueError):
        db_session.commit()
    db_session.rollback()
    original_title = version.title
    db_session.delete(version)
    with pytest.raises(ValueError):
        db_session.commit()
    db_session.rollback()
    assert db_session.get(VideoScriptVersion, version.id).title == original_title
    scene = (
        db_session.query(VideoStoryboardSceneVersion)
        .filter_by(video_script_version_id=version.id)
        .first()
    )
    original_scene = (scene.visual_description, scene.narration, scene.subtitle_draft)
    scene.narration = "mutated scene"
    with pytest.raises(ValueError):
        db_session.commit()
    db_session.rollback()
    restored_scene = db_session.get(VideoStoryboardSceneVersion, scene.id)
    assert (
        restored_scene.visual_description,
        restored_scene.narration,
        restored_scene.subtitle_draft,
    ) == original_scene
    db_session.delete(restored_scene)
    with pytest.raises(ValueError):
        db_session.commit()
    db_session.rollback()
    assert db_session.get(VideoStoryboardSceneVersion, scene.id) is not None


def immutable_rows(session, variant_id: int) -> tuple[object, ...]:
    versions = session.execute(
        text(
            "SELECT id,version_number,parent_version_id,source_digest,content_digest,"
            "title,concept,hook,full_narration,cta,full_subtitle_draft,review_status "
            "FROM video_script_versions WHERE batch_video_variant_id=:variant_id "
            "ORDER BY version_number"
        ),
        {"variant_id": variant_id},
    ).all()
    scenes = session.execute(
        text(
            "SELECT s.id,s.video_script_version_id,s.sequence,s.start_ms,s.end_ms,"
            "s.shot_type,s.visual_description,s.action_description,s.narration,"
            "s.subtitle_draft FROM video_storyboard_scene_versions s "
            "JOIN video_script_versions v ON v.id=s.video_script_version_id "
            "WHERE v.batch_video_variant_id=:variant_id "
            "ORDER BY s.video_script_version_id,s.sequence"
        ),
        {"variant_id": variant_id},
    ).all()
    return tuple(versions), tuple(scenes)


def test_activation_changes_only_pointer_and_preserves_all_history(db_session) -> None:
    variant = ready_variant(db_session)
    service = VideoScriptVersionService(db_session)
    first = service.create(
        variant.id, create_request(db_session, variant.id, key="activate-v1")
    ).version
    second = service.create(
        variant.id,
        create_request(
            db_session,
            variant.id,
            key="activate-v2",
            title="Edited",
            parent=first.id,
        ),
    ).version
    before = immutable_rows(db_session, variant.id)
    assert service.activate(variant.id, first.id).reused is False
    assert (
        db_session.get(BatchVideoVariant, variant.id).active_script_version_id
        == first.id
    )
    assert immutable_rows(db_session, variant.id) == before
    assert service.activate(variant.id, first.id).reused is True
    assert (
        db_session.get(BatchVideoVariant, variant.id).active_script_version_id
        == first.id
    )
    assert immutable_rows(db_session, variant.id) == before
    assert service.activate(variant.id, second.id).reused is False
    assert (
        db_session.get(BatchVideoVariant, variant.id).active_script_version_id
        == second.id
    )
    assert immutable_rows(db_session, variant.id) == before


def test_foreign_keys_restrict_deleting_variant_parent_and_brand(db_session) -> None:
    db_session.execute(text("PRAGMA foreign_keys=ON"))
    variant = ready_variant(db_session)
    service = VideoScriptVersionService(db_session)
    first = service.create(
        variant.id, create_request(db_session, variant.id, key="restrict-v1")
    ).version
    service.create(
        variant.id,
        create_request(
            db_session,
            variant.id,
            key="restrict-v2",
            title="Edited",
            parent=first.id,
        ),
    )
    for statement, value in (
        ("DELETE FROM batch_video_variants WHERE id=:id", variant.id),
        ("DELETE FROM video_script_versions WHERE id=:id", first.id),
        ("DELETE FROM brand_kit_versions WHERE id=:id", variant.brand_kit_version_id),
    ):
        with pytest.raises(IntegrityError):
            db_session.execute(text(statement), {"id": value})
            db_session.commit()
        db_session.rollback()
        assert db_session.get(BatchVideoVariant, variant.id) is not None
        assert db_session.get(VideoScriptVersion, first.id) is not None
    db_session.execute(text("PRAGMA foreign_keys=OFF"))
    db_session.commit()


def test_exact_identity_and_safe_not_found(db_session) -> None:
    one, two = ready_variant(db_session), ready_variant(db_session)
    version = (
        VideoScriptVersionService(db_session)
        .create(one.id, create_request(db_session, one.id, key="identity-key"))
        .version
    )
    with pytest.raises(AppError) as failure:
        VideoScriptVersionService(db_session).get(two.id, version.id)
    assert (
        failure.value.status_code == 404
        and failure.value.message == "Script version was not found"
    )


@pytest.mark.parametrize(
    "case",
    [
        "expired",
        "content changed",
        "variant digest changed",
        "product changed",
        "brand id changed",
        "brand digest changed",
        "preflight tampered",
    ],
)
def test_stale_or_tampered_preflight_is_four_way_zero_write(db_session, case) -> None:
    variant = ready_variant(db_session)
    value = draft(idempotency_key=f"stale-{case.replace(' ', '-')}")
    expires = datetime.now(UTC) - timedelta(seconds=1) if case == "expired" else None
    checked = VideoScriptPreflightService(db_session).run(
        variant.id, value, expires_at=expires
    )
    request_value = value
    overrides: dict[str, object] = {}
    if case == "content changed":
        request_value = value.model_copy(update={"title": "Changed after preflight"})
    elif case == "variant digest changed":
        variant.source_digest = "f" * 64
        db_session.commit()
    elif case == "product changed":
        product = db_session.get(Product, variant.product_id)
        assert product is not None
        product.description = "Changed after preflight"
        db_session.commit()
    elif case == "brand id changed":
        replacement = _new_brand(db_session, 9)
        variant.brand_kit_version_id = replacement.id
        variant.brand_kit_version_digest = replacement.digest
        db_session.commit()
    elif case == "brand digest changed":
        variant.brand_kit_version_digest = "e" * 64
        db_session.commit()
    elif case == "preflight tampered":
        overrides["preflight_digest"] = "0" * 64
    request = request_from_preflight(request_value, checked, **overrides)
    before = script_state(db_session, variant.id)
    with pytest.raises(AppError) as failure:
        VideoScriptVersionService(db_session).create(variant.id, request)
    assert failure.value.status_code == 409
    assert script_state(db_session, variant.id) == before


def test_cross_variant_parent_and_activation_are_safe_zero_write(db_session) -> None:
    first_variant = ready_variant(db_session)
    second_variant = ready_variant(db_session)
    first_version = (
        VideoScriptVersionService(db_session)
        .create(
            first_variant.id,
            create_request(db_session, first_variant.id, key="cross-parent-source"),
        )
        .version
    )
    before = script_state(db_session, second_variant.id)
    with pytest.raises(AppError) as parent_failure:
        create_request(
            db_session,
            second_variant.id,
            key="cross-parent-target",
            parent=first_version.id,
        )
    assert parent_failure.value.status_code == 404
    assert script_state(db_session, second_variant.id) == before
    with pytest.raises(AppError) as activation_failure:
        VideoScriptVersionService(db_session).activate(
            second_variant.id, first_version.id
        )
    assert activation_failure.value.status_code == 404
    assert activation_failure.value.message == "Script version was not found"
    assert script_state(db_session, second_variant.id) == before


def test_api_cost_fields_exact_ids_and_uniform_safe_404(client, db_session) -> None:
    variant = ready_variant(db_session)
    payload = draft(idempotency_key="api-script-key").model_dump(mode="json")
    checked = client.post(
        f"/api/v1/batch-video-variants/{variant.id}/script-versions/preflight",
        json=payload,
    )
    assert checked.status_code == 200
    assert {
        key: checked.json()[key]
        for key in (
            "current_stage_cost",
            "cost_scope",
            "provider_call_count",
            "database_writes",
            "review_status",
        )
    } == {
        "current_stage_cost": "0",
        "cost_scope": "manual_versioning_only",
        "provider_call_count": 0,
        "database_writes": 0,
        "review_status": "UNREVIEWED",
    }
    created = client.post(
        f"/api/v1/batch-video-variants/{variant.id}/script-versions",
        json={
            **payload,
            "source_digest": checked.json()["source_digest"],
            "content_digest": checked.json()["content_digest"],
            "preflight_digest": checked.json()["preflight_digest"],
            "preflight_expires_at": checked.json()["expires_at"],
        },
    )
    assert created.status_code == 201 and created.json()["reused"] is False
    version_id = created.json()["version"]["id"]
    assert created.json()["version"]["review_status"] == "UNREVIEWED"
    reused = client.post(
        f"/api/v1/batch-video-variants/{variant.id}/script-versions",
        json={
            **payload,
            "source_digest": checked.json()["source_digest"],
            "content_digest": checked.json()["content_digest"],
            "preflight_digest": checked.json()["preflight_digest"],
            "preflight_expires_at": checked.json()["expires_at"],
        },
    )
    assert reused.status_code == 201
    assert reused.json()["reused"] is True
    assert reused.json()["version"]["id"] == version_id
    listed = client.get(f"/api/v1/batch-video-variants/{variant.id}/script-versions")
    assert listed.status_code == 200
    assert [item["version_number"] for item in listed.json()] == [1]
    exact = client.get(
        f"/api/v1/batch-video-variants/{variant.id}/script-versions/{version_id}"
    )
    assert exact.status_code == 200
    assert exact.json()["id"] == version_id
    assert exact.json()["batch_video_variant_id"] == variant.id
    activated = client.post(
        f"/api/v1/batch-video-variants/{variant.id}/script-versions/"
        f"{version_id}/activate"
    )
    assert activated.status_code == 200 and activated.json()["reused"] is False
    activated_again = client.post(
        f"/api/v1/batch-video-variants/{variant.id}/script-versions/"
        f"{version_id}/activate"
    )
    assert activated_again.status_code == 200
    assert activated_again.json()["reused"] is True
    assert (
        VideoScriptVersionService(db_session).get(variant.id, version_id).review_status
        == "UNREVIEWED"
    )
    missing = client.get(
        f"/api/v1/batch-video-variants/{variant.id}/script-versions/999999"
    )
    mismatch = client.get(
        f"/api/v1/batch-video-variants/999999/script-versions/{version_id}"
    )
    assert missing.status_code == mismatch.status_code == 404
    assert (
        missing.json()
        == mismatch.json()
        == {"error": {"message": "Script version was not found"}}
    )
    wrong_activation = client.post(
        f"/api/v1/batch-video-variants/999999/script-versions/{version_id}/activate"
    )
    assert wrong_activation.status_code == 404
    assert wrong_activation.json() == missing.json()
    serialized = str(wrong_activation.json()).casefold()
    assert all(
        forbidden not in serialized
        for forbidden in ("sql", "traceback", "d:\\", "candidate", "999999")
    )
    for method in ("PUT", "PATCH", "DELETE"):
        response = client.request(
            method,
            f"/api/v1/batch-video-variants/{variant.id}/script-versions/{version_id}",
            json={},
        )
        assert response.status_code == 405


def test_two_sessions_allocate_unique_continuous_numbers(tmp_path) -> None:
    database = tmp_path / "script-concurrency.db"
    engine = create_engine(
        f"sqlite:///{database.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as setup:
        variant = ready_variant(setup)
        request_one = create_request(setup, variant.id, key="parallel-key-1")
        request_two = create_request(setup, variant.id, key="parallel-key-2")
        variant_id = variant.id
    barrier = Barrier(2)

    def save(request):
        with factory() as session:
            barrier.wait()
            return (
                VideoScriptVersionService(session)
                .create(variant_id, request)
                .version.version_number
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(save, request_one), pool.submit(save, request_two)]
        numbers = sorted(future.result() for future in futures)
    assert numbers == [1, 2]
    with factory() as verify:
        assert [
            item.version_number
            for item in VideoScriptVersionService(verify).list(variant_id)
        ] == [1, 2]
    engine.dispose()


def _new_brand(session, number: int) -> BrandKitVersion:
    kit = BrandKit(name=f"Brand {number}")
    session.add(kit)
    session.flush()
    version = BrandKitVersion(
        brand_kit_id=kit.id,
        version_number=1,
        digest=f"{number:064x}",
        brand_name=f"Brand {number}",
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
    session.add(version)
    session.flush()
    return version


def test_product_brand_rebinding_does_not_change_frozen_history(db_session) -> None:
    variant = ready_variant(db_session)
    created = (
        VideoScriptVersionService(db_session)
        .create(
            variant.id,
            create_request(db_session, variant.id, key="brand-freeze-key"),
        )
        .version
    )
    frozen = (created.brand_kit_version_id, created.brand_kit_version_digest)
    assert created.batch_video_variant_id == variant.id
    assert created.product_id == variant.product_id
    assert len(created.product_content_digest) == 64
    assert created.platform == variant.platform
    assert created.language == variant.language
    assert created.creative_angle == variant.creative_angle
    assert frozen == (variant.brand_kit_version_id, variant.brand_kit_version_digest)
    assert frozen[0] is not None and frozen[1] is not None
    assert created.strategy_id is None and created.copy_matrix_id is None
    replacement = _new_brand(db_session, 2)
    product = db_session.get(Product, variant.product_id)
    assert product is not None
    product.brand_kit_version_id = replacement.id
    db_session.commit()
    restored = VideoScriptVersionService(db_session).get(variant.id, created.id)
    assert (restored.brand_kit_version_id, restored.brand_kit_version_digest) == frozen


def test_video_project_import_freezes_exact_source_after_project_changes(
    db_session,
) -> None:
    variant = ready_variant(db_session)
    strategy = MarketingStrategy(
        product_id=variant.product_id,
        positioning="Exact",
        audience_insights=["A"],
        angles=["B"],
        risks=["C"],
        evidence=["D"],
    )
    db_session.add(strategy)
    db_session.flush()
    copies = CopyMatrix(
        product_id=variant.product_id,
        marketing_strategy_id=strategy.id,
        copies=[
            {"platform": "TikTok", "hook": "T"},
            {"platform": "Instagram", "hook": "I"},
            {"platform": "Facebook", "hook": "F"},
        ],
    )
    db_session.add(copies)
    db_session.flush()
    project = VideoProject(
        product_id=variant.product_id,
        marketing_strategy_id=strategy.id,
        copy_matrix_id=copies.id,
        platform="youtube",
        title="Imported source",
        concept="Source concept",
        duration_seconds=15,
        aspect_ratio="9:16",
        scenes=[{"sequence": 1, "duration_seconds": 15}],
        cta="Source CTA",
        status="planned",
    )
    db_session.add(project)
    db_session.commit()
    imported = draft(
        source_type="VIDEO_PROJECT_IMPORT",
        source_video_project_id=project.id,
        idempotency_key="project-import-key",
    )
    checked = VideoScriptPreflightService(db_session).run(variant.id, imported)
    request = VideoScriptCreateRequest.model_validate(
        {
            **imported.model_dump(),
            "source_digest": checked.source_digest,
            "content_digest": checked.content_digest,
            "preflight_digest": checked.preflight_digest,
            "preflight_expires_at": checked.expires_at,
        }
    )
    created = VideoScriptVersionService(db_session).create(variant.id, request).version
    frozen = (created.source_video_project_id, created.source_video_project_digest)
    project.title = "Mutated after import"
    db_session.commit()
    restored = VideoScriptVersionService(db_session).get(variant.id, created.id)
    assert (
        restored.source_video_project_id,
        restored.source_video_project_digest,
    ) == frozen
    stale_import = imported.model_copy(
        update={"idempotency_key": "project-stale-preflight-key"}
    )
    stale_checked = VideoScriptPreflightService(db_session).run(
        variant.id, stale_import
    )
    project.concept = "Mutated after stale preflight"
    db_session.commit()
    stale_request = request_from_preflight(stale_import, stale_checked)
    before = script_state(db_session, variant.id)
    with pytest.raises(AppError) as failure:
        VideoScriptVersionService(db_session).create(variant.id, stale_request)
    assert failure.value.status_code == 409
    assert script_state(db_session, variant.id) == before


def test_saved_version_owns_input_snapshot_and_derived_scene_text(db_session) -> None:
    variant = ready_variant(db_session)
    value = draft(idempotency_key="detached-input-snapshot")
    checked = VideoScriptPreflightService(db_session).run(variant.id, value)
    request = request_from_preflight(value, checked)
    created = VideoScriptVersionService(db_session).create(variant.id, request).version
    persisted_before = immutable_rows(db_session, variant.id)
    request.title = "Changed only in caller memory"
    request.scenes[0].narration = "Changed only in caller memory"
    request.scenes[0].subtitle_draft = "Changed only in caller memory"
    restored = VideoScriptVersionService(db_session).get(variant.id, created.id)
    assert immutable_rows(db_session, variant.id) == persisted_before
    assert restored.full_narration == " ".join(
        scene.narration for scene in restored.scenes
    )
    assert restored.full_subtitle_draft == " ".join(
        scene.subtitle_draft for scene in restored.scenes
    )


def test_manual_versioning_never_crosses_external_call_guards(
    db_session, monkeypatch
) -> None:
    calls = {
        "provider": 0,
        "qwen": 0,
        "wanx": 0,
        "tts": 0,
        "ffmpeg": 0,
        "publishing": 0,
        "network": 0,
    }

    def forbidden(kind: str):
        def fail(*_args, **_kwargs):
            calls[kind] += 1
            raise AssertionError(f"forbidden external boundary reached: {kind}")

        return fail

    monkeypatch.setattr(QwenProvider, "generate", forbidden("qwen"))
    monkeypatch.setattr(WanxProvider, "submit", forbidden("wanx"))
    monkeypatch.setattr(WanxProvider, "fetch", forbidden("wanx"))
    monkeypatch.setattr(YouTubeProvider, "upload_media", forbidden("publishing"))
    monkeypatch.setattr(YouTubeProvider, "upload_video", forbidden("publishing"))
    monkeypatch.setattr(InstagramProvider, "upload_reel_bytes", forbidden("publishing"))
    monkeypatch.setattr(InstagramProvider, "publish_reel", forbidden("publishing"))
    monkeypatch.setattr(TikTokProvider, "upload_video_chunk", forbidden("publishing"))
    monkeypatch.setattr(TikTokProvider, "fetch_publish_status", forbidden("publishing"))
    monkeypatch.setattr(subprocess, "run", forbidden("ffmpeg"))
    monkeypatch.setattr(subprocess, "Popen", forbidden("tts"))
    monkeypatch.setattr(socket, "create_connection", forbidden("network"))

    variant = ready_variant(db_session)
    service = VideoScriptVersionService(db_session)
    request = create_request(db_session, variant.id, key="external-guard-key")
    created = service.create(variant.id, request)
    reused = service.create(variant.id, request)
    activated = service.activate(variant.id, created.version.id)

    assert created.reused is False
    assert reused.reused is True
    assert activated.active_script_version_id == created.version.id
    assert calls == {key: 0 for key in calls}

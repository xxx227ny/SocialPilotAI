import hashlib
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import (
    BatchVideoJob,
    BatchVideoVariant,
    MarketingStrategy,
    Product,
    ProductAsset,
    ProductVideoProductionBatch,
    ProductVideoProductionItem,
    VideoComposition,
    VideoCompositionArtifact,
    VideoCompositionAudioArtifact,
    VideoCompositionEnhancement,
    VideoCompositionEnhancementArtifact,
    VideoCompositionSubtitleArtifact,
    VideoProject,
    VideoRenderArtifact,
    VideoRenderTask,
    VideoScriptVersion,
)
from app.services.auto_social_publish_service import (
    AutoSocialPublishService,
    _product_tags,
    _youtube_tag_length,
)
from app.services.social_publish_source import SocialPublishSourceService
from app.services.video_artifact_storage import LocalVideoArtifactStorage


def test_youtube_product_tags_remove_breadcrumbs_and_use_documented_limit() -> None:
    product = Product(
        name=(
            "VitaBlend Portable Blender - Personal Size USB Rechargeable "
            "Smoothie Maker with 6 Blades"
        ),
        category="Home & Kitchen > Kitchen & Dining > Small Appliances",
        selling_points=["A very long selling point " * 8, "Blend anywhere"],
        target_markets=["US"],
    )

    tags = _product_tags(product, include_shorts=True)

    assert tags
    assert "Shorts" in tags
    assert all("<" not in tag and ">" not in tag for tag in tags)
    assert all(len(tag) <= 60 for tag in tags)
    assert _youtube_tag_length(tags) <= 500
    assert "Kitchen & Dining" in tags


@pytest.mark.parametrize(
    ("platform", "project_platform"),
    [("youtube", "YouTube Shorts"), ("instagram", "Instagram Reels")],
)
def test_auto_draft_pins_complete_final_video_and_generates_copy(
    db_session: Session, tmp_path, platform: str, project_platform: str
) -> None:
    settings = Settings(
        _env_file=None,
        video_artifact_storage_root=str(tmp_path.resolve()),
    )
    storage = LocalVideoArtifactStorage(tmp_path.resolve(), 1_000_000)
    product = Product(
        name="Portable Demo Lamp",
        category="Lighting",
        description="A compact lamp.",
        selling_points=["Portable", "Warm light"],
        target_markets=["US"],
    )
    db_session.add(product)
    db_session.flush()
    strategy = MarketingStrategy(
        product_id=product.id,
        positioning="Useful light anywhere",
        audience_insights=["People who need portable light"],
        angles=["Show the lamp in use"],
        risks=["No unsupported claims"],
        evidence=["Product facts"],
    )
    asset = ProductAsset(
        product_id=product.id,
        file_name="lamp.png",
        file_path="lamp.png",
        file_type="png",
        content_type="image/png",
        size_bytes=10,
        sha256="a" * 64,
        storage_identity=f"lamp-{platform}.png",
    )
    batch_job = BatchVideoJob(
        request_digest="b" * 64,
        idempotency_key=f"auto-draft-batch-{platform}",
        status="READY_FOR_SCRIPT",
        priority=50,
        variant_count=1,
        max_concurrency=1,
        current_stage_cost=Decimal("0"),
        currency="USD",
        cost_scope="orchestration_only",
        downstream_provider_cost_status="NOT_ESTIMATED",
        cost_confirmed=True,
        frozen_constraints_json={},
    )
    db_session.add_all([strategy, asset, batch_job])
    db_session.flush()
    variant = BatchVideoVariant(
        batch_video_job_id=batch_job.id,
        product_id=product.id,
        platform=platform,
        variant_index=1,
        duration_seconds=15,
        aspect_ratio="9:16",
        language="en-US",
        source_digest="c" * 64,
        idempotency_key=f"auto-draft-variant-{platform}",
        status="READY_FOR_SCRIPT",
        result_entity_type="batch_video_variant",
        result_entity_id=1,
    )
    db_session.add(variant)
    db_session.flush()
    script = VideoScriptVersion(
        batch_video_variant_id=variant.id,
        version_number=1,
        source_type="QWEN_GENERATED",
        source_digest="d" * 64,
        content_digest="e" * 64,
        idempotency_key=f"auto-draft-script-{platform}",
        product_id=product.id,
        product_content_digest="f" * 64,
        strategy_id=strategy.id,
        strategy_digest="1" * 64,
        platform=platform,
        language="en-US",
        title="Portable light in 15 seconds",
        concept="Product demonstration",
        hook="Light anywhere in seconds.",
        full_narration="Open the lamp and enjoy warm portable light.",
        cta="Learn more today.",
        full_subtitle_draft="Open the lamp.",
        created_by_kind="QWEN_PROVIDER",
        review_status="UNREVIEWED",
    )
    db_session.add(script)
    db_session.flush()
    variant.active_script_version_id = script.id
    variant.script_version_sequence = 1
    project = VideoProject(
        product_id=product.id,
        marketing_strategy_id=strategy.id,
        copy_matrix_id=None,
        platform=project_platform,
        title=script.title,
        concept=script.concept,
        duration_seconds=15,
        aspect_ratio="9:16",
        scenes=[],
        cta=script.cta,
        status="planned",
        source_script_version_id=script.id,
        source_script_content_digest=script.content_digest,
        source_input_digest=("2" if platform == "youtube" else "3") * 64,
    )
    db_session.add(project)
    db_session.flush()
    render_task = VideoRenderTask(
        video_project_id=project.id,
        scene_sequence=1,
        status="SUCCEEDED",
        provider_name="fake",
        provider_task_id=f"provider-{platform}",
        render_prompt="show product",
        duration_seconds=5,
        aspect_ratio="9:16",
        resolution="1080x1920",
        idempotency_key=f"auto-draft-render-{platform}",
    )
    db_session.add(render_task)
    db_session.flush()
    stored_render = storage.store(
        task_id=render_task.id,
        content=b"scene-render",
        content_type="video/mp4",
    )
    render_artifact = VideoRenderArtifact(
        video_render_task_id=render_task.id,
        storage_path=stored_render.relative_path,
        artifact_metadata={
            "content_type": stored_render.content_type,
            "size_bytes": stored_render.size_bytes,
            "sha256": stored_render.sha256,
        },
    )
    db_session.add(render_artifact)
    db_session.flush()
    composition = VideoComposition(
        product_id=product.id,
        video_project_id=project.id,
        input_digest="4" * 64,
        source_chain_digest="5" * 64,
        idempotency_key=f"auto-draft-composition-{platform}",
        status="SUCCEEDED",
    )
    db_session.add(composition)
    db_session.flush()
    composition_artifact = VideoCompositionArtifact(
        composition_id=composition.id,
        storage_path=f"composition-{platform}.mp4",
        content_type="video/mp4",
        size_bytes=10,
        sha256="6" * 64,
        duration_ms=15000,
        width=1080,
        height=1920,
        fps_numerator=30,
        fps_denominator=1,
        video_codec="h264",
        pixel_format="yuv420p",
        audio_codec="aac",
        audio_sample_rate=48000,
        container="mp4",
        source_chain_digest=composition.source_chain_digest,
    )
    voice = VideoCompositionAudioArtifact(
        product_id=product.id,
        video_project_id=project.id,
        composition_id=composition.id,
        kind="voiceover",
        storage_path=f"voice-{platform}.wav",
        content_type="audio/wav",
        size_bytes=10,
        sha256="7" * 64,
        duration_ms=15000,
    )
    db_session.add_all([composition_artifact, voice])
    db_session.flush()
    enhancement = VideoCompositionEnhancement(
        product_id=product.id,
        video_project_id=project.id,
        composition_id=composition.id,
        source_artifact_id=composition_artifact.id,
        voiceover_artifact_id=voice.id,
        music_artifact_id=None,
        input_digest="8" * 64,
        source_chain_digest="9" * 64,
        idempotency_key=f"auto-draft-enhancement-{platform}",
        subtitle_cues_json=[{"start_ms": 0, "end_ms": 15000, "text": "Demo"}],
        subtitle_style_json={},
        voiceover_gain_millidb=0,
        music_gain_millidb=-18000,
        ducking_reduction_millidb=9000,
        target_lufs_milli=-14000,
        true_peak_millidb=-1000,
        status="SUCCEEDED",
    )
    db_session.add(enhancement)
    db_session.flush()
    subtitle_content = b"WEBVTT\n\n00:00:00.000 --> 00:00:15.000\nDemo\n"
    subtitle = VideoCompositionSubtitleArtifact(
        enhancement_id=enhancement.id,
        storage_path=f"subtitle-{platform}.vtt",
        content_type="text/vtt; charset=utf-8",
        size_bytes=len(subtitle_content),
        sha256=hashlib.sha256(subtitle_content).hexdigest(),
        format="webvtt",
        cue_count=1,
    )
    db_session.add(subtitle)
    db_session.flush()
    final_content = f"complete-final-video-{platform}".encode()
    final_name = f"final-{platform}.mp4"
    (tmp_path / final_name).write_bytes(final_content)
    final = VideoCompositionEnhancementArtifact(
        enhancement_id=enhancement.id,
        subtitle_artifact_id=subtitle.id,
        storage_path=final_name,
        content_type="video/mp4",
        size_bytes=len(final_content),
        sha256=hashlib.sha256(final_content).hexdigest(),
        duration_ms=15000,
        width=1080,
        height=1920,
        fps_numerator=30,
        fps_denominator=1,
        video_codec="h264",
        video_profile="high",
        pixel_format="yuv420p",
        audio_codec="aac",
        audio_profile="lc",
        audio_sample_rate=48000,
        audio_channels=2,
        container="mp4",
        measured_lufs_milli=-14000,
        measured_true_peak_millidb=-1000,
        audio_video_sync_offset_ms=0,
        longest_black_segment_ms=0,
        subtitle_format="webvtt",
        subtitle_cue_count=1,
        subtitle_sha256=subtitle.sha256,
        source_chain_digest=enhancement.source_chain_digest,
    )
    db_session.add(final)
    db_session.flush()
    production_batch = ProductVideoProductionBatch(
        product_id=product.id,
        reference_product_asset_id=asset.id,
        reference_product_asset_sha256=asset.sha256,
        input_digest="a" * 64,
        idempotency_key=f"auto-draft-production-{platform}",
        status="SUCCEEDED",
        known_estimated_cost=Decimal("0"),
        currency="USD",
        cost_estimate_complete=True,
        cost_confirmed=True,
        provider_call_budget=1,
        frozen_preflight_json={},
    )
    db_session.add(production_batch)
    db_session.flush()
    item = ProductVideoProductionItem(
        production_batch_id=production_batch.id,
        batch_video_variant_id=variant.id,
        script_version_id=script.id,
        platform=platform,
        status="SUCCEEDED",
        stage="COMPLETE",
        stage_state_json={},
        video_project_id=project.id,
        cloud_render_task_id=render_task.id,
        cloud_render_artifact_id=render_artifact.id,
        composition_id=composition.id,
        voiceover_artifact_id=voice.id,
        enhancement_id=enhancement.id,
        final_video_artifact_id=final.id,
        subtitle_artifact_id=subtitle.id,
    )
    db_session.add(item)
    db_session.commit()

    source = SocialPublishSourceService(db_session, settings, storage).latest_final(
        product_id=product.id, platform=platform
    )
    draft = AutoSocialPublishService(db_session, settings, storage).draft(
        product.id, platform
    )

    assert source.path == tmp_path / final_name
    assert source.path.read_bytes() == final_content
    assert source.artifact.id == render_artifact.id
    assert source.final_video_artifact_id == final.id
    assert draft.artifact_id == render_artifact.id
    assert draft.final_video_artifact_id == final.id
    assert draft.production_item_id == item.id
    assert draft.complete_final_video is True
    assert draft.duration_seconds == 15
    assert draft.title == script.title
    assert draft.description
    if platform == "youtube":
        assert product.name in draft.tags
    else:
        assert "PortableDemoLamp" in draft.tags
        assert all(" " not in tag for tag in draft.tags)
        caption = f"{draft.description}\n\n" + " ".join(
            f"#{tag}" for tag in draft.tags
        )
        assert len(caption) <= 2200

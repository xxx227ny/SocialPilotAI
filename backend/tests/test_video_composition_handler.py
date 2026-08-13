from pathlib import Path
from threading import Event
from unittest.mock import patch

from app.core.config import Settings
from app.core.exceptions import AppError
from app.execution.contracts import ExecutionContext, HandlerStatus
from app.execution.handlers.video_composition import (
    VideoCompositionRenderV1Handler,
    VideoCompositionRenderV1Input,
)
from app.models import Product, VideoComposition, VideoCompositionArtifact, VideoProject


def _settings(root: Path) -> Settings:
    return Settings(
        _env_file=None,
        enable_video_composition=True,
        video_artifact_storage_root=str(root),
        video_composition_temp_root=str(root / "temp"),
    )


def _composition(db_session):
    product = Product(
        name="P",
        category="C",
        description="D",
        selling_points=["S"],
        target_markets=["USA"],
    )
    db_session.add(product)
    db_session.flush()
    project = VideoProject(
        product_id=product.id,
        marketing_strategy_id=1,
        copy_matrix_id=1,
        platform="TikTok",
        title="T",
        concept="C",
        duration_seconds=15,
        aspect_ratio="9:16",
        scenes=[],
        cta="C",
        status="planned",
    )
    db_session.add(project)
    db_session.flush()
    composition = VideoComposition(
        product_id=product.id,
        video_project_id=project.id,
        input_digest="a" * 64,
        source_chain_digest="b" * 64,
        idempotency_key="handler-composition",
        status="QUEUED",
    )
    db_session.add(composition)
    db_session.commit()
    return composition


def _context():
    return ExecutionContext(
        job_id=1,
        stop_event=Event(),
        lease_lost_event=Event(),
        heartbeat=lambda _count, _external: None,
    )


def _payload(composition):
    return VideoCompositionRenderV1Input(
        composition_id=composition.id,
        product_id=composition.product_id,
        video_project_id=composition.video_project_id,
        frozen_input_digest=composition.input_digest,
        frozen_source_chain_digest=composition.source_chain_digest,
    )


def test_handler_returns_exact_artifact_identity(db_session, tmp_path) -> None:
    settings = _settings(tmp_path)
    composition = _composition(db_session)
    artifact = VideoCompositionArtifact(
        composition_id=composition.id,
        storage_path="fake.mp4",
        content_type="video/mp4",
        size_bytes=4,
        sha256="c" * 64,
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
    db_session.add(artifact)
    db_session.commit()
    def session_factory():
        return db_session

    with patch(
        "app.execution.handlers.video_composition.VideoCompositionService.render",
        return_value=artifact,
    ):
        result = VideoCompositionRenderV1Handler(
            session_factory=session_factory,
            settings=settings,
        ).execute(_context(), _payload(composition))
    assert result.status == HandlerStatus.SUCCEEDED
    assert result.provider_name == "local_ffmpeg"
    assert result.result_entity_type == "video_composition_artifact"
    assert result.result_entity_id == artifact.id


def test_handler_rejects_changed_frozen_identity_before_render(
    db_session, tmp_path
) -> None:
    settings = _settings(tmp_path)
    composition = _composition(db_session)
    payload = _payload(composition).model_copy(
        update={"frozen_input_digest": "d" * 64}
    )
    with patch(
        "app.execution.handlers.video_composition.VideoCompositionService.render"
    ) as render:
        result = VideoCompositionRenderV1Handler(
            session_factory=lambda: db_session,
            settings=settings,
        ).execute(_context(), payload)
    assert result.status == HandlerStatus.FAILED
    assert render.call_count == 0


def test_handler_preserves_persist_unknown(db_session, tmp_path) -> None:
    settings = _settings(tmp_path)
    composition = _composition(db_session)

    def uncertain(*_args):
        composition.status = "PERSIST_UNKNOWN"
        composition.safe_error_code = "COMPOSITION_RESULT_PERSIST_UNKNOWN"
        db_session.commit()
        raise AppError("uncertain", 500)
    with patch(
        "app.execution.handlers.video_composition.VideoCompositionService.render",
        side_effect=uncertain,
    ):
        result = VideoCompositionRenderV1Handler(
            session_factory=lambda: db_session,
            settings=settings,
        ).execute(_context(), _payload(composition))
    assert result.status == HandlerStatus.SUBMIT_UNKNOWN
    assert result.safe_error_code == "COMPOSITION_RESULT_PERSIST_UNKNOWN"

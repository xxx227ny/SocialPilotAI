from threading import Event
from unittest.mock import patch

import pytest

from app.core.exceptions import AppError
from app.execution.contracts import ExecutionContext, HandlerStatus
from app.execution.handlers.video_composition_enhancement import (
    VideoCompositionEnhanceV1Handler,
    VideoCompositionEnhanceV1Input,
)
from app.models import VideoCompositionEnhancement, VideoCompositionEnhancementArtifact
from app.schemas.video_composition_enhancement import (
    VideoCompositionEnhancementSubmitRequest,
)
from app.services.video_composition_enhancement_job_service import (
    VideoCompositionEnhancementJobService,
)
from app.services.video_composition_enhancement_preflight import (
    VideoCompositionEnhancementPreflightService,
)
from tests.test_video_composition_enhancement import (
    _request,
    _settings,
    _sha,
    _source,
)


def _context(job_id: int) -> ExecutionContext:
    return ExecutionContext(
        job_id=job_id,
        stop_event=Event(),
        lease_lost_event=Event(),
        heartbeat=lambda *_: None,
    )


def _queued(db_session, tmp_path):
    product, project, composition, source, voice, music = _source(
        db_session, tmp_path
    )
    settings = _settings(tmp_path)
    request = _request(composition, source, voice, music)
    preflight = VideoCompositionEnhancementPreflightService(
        db_session, settings
    ).run(product.id, request)
    submit = VideoCompositionEnhancementSubmitRequest(
        **request.model_dump(),
        input_digest=preflight.input_digest,
        source_chain_digest=preflight.source_chain_digest,
        preflight_digest=preflight.preflight_digest,
        preflight_expires_at=preflight.expires_at,
        local_cpu_cost_confirmed=True,
    )
    queued = VideoCompositionEnhancementJobService(db_session, settings).enqueue(
        product.id, submit
    )
    payload = VideoCompositionEnhanceV1Input.model_validate(queued.job.input_payload)
    return queued, payload, settings


def test_enhancement_handler_returns_exact_result(db_session, tmp_path) -> None:
    queued, payload, settings = _queued(db_session, tmp_path)
    artifact = VideoCompositionEnhancementArtifact(
        id=41,
        enhancement_id=queued.enhancement.id,
    )

    def session_factory():
        return db_session

    with patch(
        "app.execution.handlers.video_composition_enhancement."
        "VideoCompositionEnhancementService.enhance",
        return_value=artifact,
    ) as enhance:
        result = VideoCompositionEnhanceV1Handler(
            session_factory=session_factory, settings=settings
        ).execute(_context(queued.job.id), payload)
    assert result.status == HandlerStatus.SUCCEEDED
    assert result.provider_name == "local_ffmpeg"
    assert result.result_entity_type == "video_composition_enhancement_artifact"
    assert result.result_entity_id == 41
    enhance.assert_called_once()
    called_id = enhance.call_args.args[0]
    before_persist = enhance.call_args.kwargs["before_persist"]
    assert called_id == queued.enhancement.id
    assert callable(before_persist)


@pytest.mark.parametrize(
    "field",
    [
        "product_id",
        "video_project_id",
        "composition_id",
        "source_artifact_id",
        "voiceover_artifact_id",
        "music_artifact_id",
        "frozen_input_digest",
        "frozen_source_chain_digest",
    ],
)
def test_enhancement_handler_rejects_frozen_change_before_ffmpeg(
    db_session, tmp_path, field
) -> None:
    queued, payload, settings = _queued(db_session, tmp_path)
    replacement = (
        "f" * 64
        if field in {"frozen_input_digest", "frozen_source_chain_digest"}
        else (payload.music_artifact_id or 0) + 1000
    )
    changed = payload.model_copy(update={field: replacement})

    def session_factory():
        return db_session

    with patch(
        "app.execution.handlers.video_composition_enhancement."
        "VideoCompositionEnhancementService.enhance"
    ) as enhance:
        result = VideoCompositionEnhanceV1Handler(
            session_factory=session_factory, settings=settings
        ).execute(_context(queued.job.id), changed)
    assert result.status == HandlerStatus.FAILED
    assert result.safe_error_code == "ENHANCEMENT_FROZEN_IDENTITY_MISMATCH"
    enhance.assert_not_called()


def test_enhancement_handler_maps_persist_unknown_without_retry(
    db_session, tmp_path
) -> None:
    queued, payload, settings = _queued(db_session, tmp_path)

    def session_factory():
        return db_session

    def uncertain(_service, enhancement_id, *, before_persist):
        before_persist()
        enhancement = db_session.get(VideoCompositionEnhancement, enhancement_id)
        enhancement.status = "PERSIST_UNKNOWN"
        enhancement.safe_error_code = "ENHANCEMENT_RESULT_PERSIST_UNKNOWN"
        db_session.commit()
        raise AppError("uncertain", 500)

    with patch(
        "app.execution.handlers.video_composition_enhancement."
        "VideoCompositionEnhancementService.enhance",
        autospec=True,
        side_effect=uncertain,
    ) as enhance:
        result = VideoCompositionEnhanceV1Handler(
            session_factory=session_factory, settings=settings
        ).execute(_context(queued.job.id), payload)
    assert result.status == HandlerStatus.SUBMIT_UNKNOWN
    assert result.safe_error_code == "ENHANCEMENT_RESULT_PERSIST_UNKNOWN"
    assert result.provider_name == "local_ffmpeg"
    assert enhance.call_count == 1


def test_enhancement_handler_maps_explicit_ffmpeg_failure_to_failed(
    db_session, tmp_path
) -> None:
    queued, payload, settings = _queued(db_session, tmp_path)

    def session_factory():
        return db_session

    with patch(
        "app.execution.handlers.video_composition_enhancement."
        "VideoCompositionEnhancementService.enhance",
        side_effect=AppError("render failed", 500),
    ) as enhance:
        result = VideoCompositionEnhanceV1Handler(
            session_factory=session_factory,
            settings=settings,
        ).execute(_context(queued.job.id), payload)
    assert result.status == HandlerStatus.FAILED
    assert result.safe_error_code == "ENHANCEMENT_RENDER_FAILED"
    assert enhance.call_count == 1


@pytest.mark.parametrize("source", ["composition", "video", "voiceover", "music"])
def test_enhancement_handler_recomputes_frozen_sources_before_ffmpeg(
    db_session,
    tmp_path,
    source,
) -> None:
    queued, payload, settings = _queued(db_session, tmp_path)
    enhancement = db_session.get(
        VideoCompositionEnhancement,
        queued.enhancement.id,
    )
    if source == "composition":
        enhancement.composition.input_digest = "e" * 64
    else:
        artifact = {
            "video": enhancement.source_artifact,
            "voiceover": enhancement.voiceover_artifact,
            "music": enhancement.music_artifact,
        }[source]
        changed = f"changed-{source}".encode()
        (tmp_path / artifact.storage_path).write_bytes(changed)
        artifact.size_bytes = len(changed)
        artifact.sha256 = _sha(changed)
    db_session.commit()

    def session_factory():
        return db_session

    with patch(
        "app.services.video_composition_enhancement_ffmpeg."
        "VideoCompositionEnhancementFFmpeg.render",
    ) as render:
        result = VideoCompositionEnhanceV1Handler(
            session_factory=session_factory,
            settings=settings,
        ).execute(_context(queued.job.id), payload)
    assert result.status == HandlerStatus.FAILED
    assert result.safe_error_code == "ENHANCEMENT_RENDER_FAILED"
    render.assert_not_called()

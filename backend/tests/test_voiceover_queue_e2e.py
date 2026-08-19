import hashlib
import io
import wave
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.execution.handlers.voiceover_tts import VoiceoverGenerateV1Handler
from app.execution.registry import ExecutionHandlerRegistry
from app.execution.worker import ExecutionWorker, WorkerRunStatus
from app.models import (
    ExecutionAttempt,
    ExecutionJob,
    Product,
    VideoComposition,
    VideoCompositionArtifact,
    VideoCompositionAudioArtifact,
    VideoProject,
    VideoScriptVersion,
)
from app.schemas.product_marketing_video import VoiceoverSubmitRequest
from app.schemas.video_composition_enhancement import (
    SubtitleCueInput,
    VideoCompositionEnhancementPreflightRequest,
)
from app.services.tts_provider import TtsExplicitFailure, TtsSubmissionUnknown
from app.services.video_composition_enhancement_preflight import (
    VideoCompositionEnhancementPreflightService,
)
from app.services.voiceover_generation_service import VoiceoverGenerationService


def _wav(frames: int) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(48000)
        wav.writeframes(b"\x01\x00\x01\x00" * frames)
    return output.getvalue()


class FakeTts:
    provider_name = "fake_local_tts"

    def __init__(self, frames: int = 4800) -> None:
        self.calls = 0
        self.content = _wav(frames)

    def generate(self, **_: object) -> bytes:
        self.calls += 1
        return self.content


def _source(
    session: Session, root: Path, suffix: str
) -> tuple[Product, VideoComposition, VideoScriptVersion]:
    product = Product(
        name=f"Product {suffix}",
        category="Demo",
        description="A sufficiently detailed fictional product description.",
        selling_points=["Portable"],
        target_markets=["US"],
    )
    session.add(product)
    session.flush()
    narration = "Fresh smoothies anywhere. Blend fresh. Go anywhere."
    version = VideoScriptVersion(
        batch_video_variant_id=1000 + product.id,
        version_number=1,
        parent_version_id=None,
        source_type="MANUAL",
        source_digest="1" * 64,
        content_digest="2" * 64,
        idempotency_key=f"script-{suffix}",
        product_id=product.id,
        product_content_digest="3" * 64,
        strategy_id=None,
        strategy_digest=None,
        copy_matrix_id=None,
        target_platform_copy_digest=None,
        source_video_project_id=None,
        source_video_project_digest=None,
        platform="tiktok",
        language="en-US",
        creative_angle="portable",
        brand_kit_version_id=None,
        brand_kit_version_digest=None,
        title="Portable blender",
        concept="Blend anywhere",
        hook="Fresh smoothies anywhere.",
        full_narration=narration,
        cta="Blend fresh. Go anywhere.",
        full_subtitle_draft=narration,
        created_by_kind="LOCAL_USER",
        review_status="UNREVIEWED",
    )
    session.add(version)
    session.flush()
    project = VideoProject(
        product_id=product.id,
        marketing_strategy_id=1000 + product.id,
        copy_matrix_id=1000 + product.id,
        platform="TikTok",
        title="Portable blender",
        concept="Blend anywhere",
        duration_seconds=15,
        aspect_ratio="9:16",
        scenes=[],
        cta="Blend fresh. Go anywhere.",
        source_script_version_id=version.id,
        source_script_content_digest=version.content_digest,
    )
    session.add(project)
    session.flush()
    composition = VideoComposition(
        product_id=product.id,
        video_project_id=project.id,
        input_digest="4" * 64,
        source_chain_digest="5" * 64,
        idempotency_key=f"composition-{suffix}",
        duration_ms=15000,
        aspect_ratio="9:16",
        width=1080,
        height=1920,
        fps_numerator=30,
        fps_denominator=1,
        status="SUCCEEDED",
    )
    session.add(composition)
    session.flush()
    video = root / f"source-{suffix}.mp4"
    video.write_bytes(b"isolated-video-artifact")
    session.add(
        VideoCompositionArtifact(
            composition_id=composition.id,
            storage_path=video.name,
            content_type="video/mp4",
            size_bytes=video.stat().st_size,
            sha256=hashlib.sha256(video.read_bytes()).hexdigest(),
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
    )
    session.commit()
    return product, composition, version


def _request(
    composition: VideoComposition, version: VideoScriptVersion, suffix: str
) -> VoiceoverSubmitRequest:
    return VoiceoverSubmitRequest(
        composition_id=composition.id,
        script_version_id=version.id,
        language="en-US",
        voice="Fake",
        speaking_rate=1,
        narration_digest=hashlib.sha256(version.full_narration.encode()).hexdigest(),
        idempotency_key=f"voiceover-{suffix}",
    )


def _worker(session: Session, settings: Settings, provider: FakeTts) -> ExecutionWorker:
    sessions = sessionmaker(
        bind=session.get_bind(), autoflush=False, expire_on_commit=False
    )
    registry = ExecutionHandlerRegistry()
    registry.register(
        VoiceoverGenerateV1Handler(
            session_factory=sessions, settings=settings, provider=provider
        )
    )
    return ExecutionWorker(
        session_factory=sessions,
        registry=registry,
        worker_id="voiceover-test-worker",
        lease_seconds=30,
        heartbeat_interval_seconds=1,
    )


def test_short_voiceover_is_padded_by_worker_and_full_timeline_preflight_passes(
    db_session: Session, tmp_path: Path
) -> None:
    settings = Settings(
        enable_real_product_video=True,
        video_artifact_storage_root=str(tmp_path),
    )
    product, composition, version = _source(db_session, tmp_path, "short")
    provider = FakeTts(frames=480000)
    request = _request(composition, version, "short")
    first = VoiceoverGenerationService(db_session, settings).enqueue(
        product.id, request
    )
    second = VoiceoverGenerationService(db_session, settings).enqueue(
        product.id, request
    )
    assert first.reused is False and second.reused is True
    assert first.job.id == second.job.id
    assert first.job.input_payload["target_duration_ms"] == 15000
    expected_digest = hashlib.sha256(
        f"{composition.id}:{version.id}:{request.narration_digest}:en-US:"
        "Fake:1.000:15000".encode()
    ).hexdigest()
    assert first.job.input_digest == expected_digest

    worker = _worker(db_session, settings, provider)
    assert worker.run_once().status == WorkerRunStatus.SUCCEEDED
    assert worker.run_once().status == WorkerRunStatus.NO_JOB
    db_session.expire_all()
    job = db_session.get(ExecutionJob, first.job.id)
    attempt = (
        db_session.query(ExecutionAttempt).filter_by(execution_job_id=job.id).one()
    )
    artifact = db_session.get(VideoCompositionAudioArtifact, job.result_entity_id)
    assert job.status == attempt.status == "SUCCEEDED"
    assert attempt.provider_call_count == provider.calls == 1
    assert artifact.natural_duration_ms == 10000
    assert artifact.duration_ms == 15000
    stored = (tmp_path / artifact.storage_path).read_bytes()
    with wave.open(io.BytesIO(provider.content), "rb") as natural_wav:
        natural_pcm = natural_wav.readframes(natural_wav.getnframes())
    with wave.open(io.BytesIO(stored), "rb") as normalized_wav:
        normalized_pcm = normalized_wav.readframes(normalized_wav.getnframes())
        assert normalized_wav.getnframes() == 720000
    assert normalized_pcm[: len(natural_pcm)] == natural_pcm
    assert normalized_pcm[len(natural_pcm) :] == b"\x00" * (240000 * 4)

    source = (
        db_session.query(VideoCompositionArtifact)
        .filter_by(composition_id=composition.id)
        .one()
    )
    preflight = VideoCompositionEnhancementPreflightService(db_session, settings).run(
        product.id,
        VideoCompositionEnhancementPreflightRequest(
            composition_id=composition.id,
            source_artifact_id=source.id,
            voiceover_artifact_id=artifact.id,
            cues=[
                SubtitleCueInput(sequence=1, start_ms=0, end_ms=5000, text="Fresh"),
                SubtitleCueInput(sequence=2, start_ms=5000, end_ms=10000, text="Blend"),
                SubtitleCueInput(sequence=3, start_ms=10000, end_ms=15000, text="Go"),
            ],
        ),
    )
    assert preflight.ready is True


def test_equal_voiceover_is_not_rewritten() -> None:
    natural = _wav(720000)
    normalized, natural_ms, duration_ms = VoiceoverGenerationService._normalize_wav(
        natural, 15000
    )
    assert normalized is natural
    assert natural_ms == duration_ms == 15000


def test_long_voiceover_fails_once_without_artifact_or_truncation(
    db_session: Session, tmp_path: Path
) -> None:
    settings = Settings(
        enable_real_product_video=True,
        video_artifact_storage_root=str(tmp_path),
    )
    product, composition, version = _source(db_session, tmp_path, "long")
    provider = FakeTts(frames=768000)
    submitted = VoiceoverGenerationService(db_session, settings).enqueue(
        product.id, _request(composition, version, "long")
    )
    worker = _worker(db_session, settings, provider)
    assert worker.run_once().status == WorkerRunStatus.FAILED
    assert worker.run_once().status == WorkerRunStatus.NO_JOB
    db_session.expire_all()
    job = db_session.get(ExecutionJob, submitted.job.id)
    attempt = (
        db_session.query(ExecutionAttempt).filter_by(execution_job_id=job.id).one()
    )
    assert job.status == attempt.status == "FAILED"
    assert (
        job.safe_error_code == attempt.safe_error_code == "VOICEOVER_EXCEEDS_TIMELINE"
    )
    assert attempt.provider_submission_state == "RESPONSE_RECEIVED"
    assert attempt.provider_call_count == provider.calls == 1
    assert job.result_entity_id is None
    assert (
        db_session.query(VideoCompositionAudioArtifact)
        .filter_by(composition_id=composition.id)
        .count()
        == 0
    )
    with wave.open(io.BytesIO(provider.content), "rb") as wav:
        assert wav.getnframes() == 768000


def test_fake_tts_contract_is_stereo_48khz_and_called_once() -> None:
    provider = FakeTts()
    content = provider.generate(text="hello", language="en", voice="fake", rate=1)
    with wave.open(io.BytesIO(content), "rb") as wav:
        assert wav.getframerate() == 48000
        assert wav.getnchannels() == 2
    assert provider.calls == 1


def test_tts_failure_categories_remain_distinct() -> None:
    assert not issubclass(TtsExplicitFailure, TtsSubmissionUnknown)

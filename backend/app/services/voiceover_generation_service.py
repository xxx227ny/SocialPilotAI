from __future__ import annotations

import hashlib
import io
import os
import tempfile
import wave
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.models import (
    ExecutionJob,
    VideoComposition,
    VideoCompositionAudioArtifact,
    VideoProject,
    VideoScriptVersion,
)
from app.schemas.execution import ExecutionJobRead
from app.schemas.product_marketing_video import JobSubmitRead, VoiceoverSubmitRequest
from app.services.tts_provider import TtsProvider

VOICEOVER_GENERATE_V1 = "tts.voiceover.generate.v1"


class VoiceoverExceedsTimeline(AppError):
    def __init__(self, natural_duration_ms: int, target_duration_ms: int) -> None:
        self.natural_duration_ms = natural_duration_ms
        self.target_duration_ms = target_duration_ms
        super().__init__("Voiceover exceeds frozen composition timeline", 422)


class VoiceoverGenerationService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session, self.settings = session, settings

    def enqueue(self, product_id: int, data: VoiceoverSubmitRequest) -> JobSubmitRead:
        if not self.settings.enable_real_product_video:
            raise AppError("Real product video execution is disabled", 503)
        composition = self.session.get(VideoComposition, data.composition_id)
        version = self.session.get(VideoScriptVersion, data.script_version_id)
        project = (
            self.session.get(VideoProject, composition.video_project_id)
            if composition
            else None
        )
        narration_digest = (
            hashlib.sha256(version.full_narration.encode()).hexdigest()
            if version
            else ""
        )
        if (
            composition is None
            or version is None
            or project is None
            or composition.product_id != product_id
            or version.product_id != product_id
            or project.source_script_version_id != version.id
            or project.source_script_content_digest != version.content_digest
            or narration_digest != data.narration_digest
        ):
            raise AppError("Voiceover frozen identity mismatch", 409)
        target_duration_ms = composition.duration_ms
        input_digest = hashlib.sha256(
            f"{composition.id}:{version.id}:{data.narration_digest}:{data.language}:"
            f"{data.voice}:{data.speaking_rate:.3f}:{target_duration_ms}".encode()
        ).hexdigest()
        key = f"{VOICEOVER_GENERATE_V1}:{data.idempotency_key}"
        existing = (
            self.session.query(ExecutionJob)
            .filter_by(idempotency_key=key)
            .one_or_none()
        )
        if existing is not None:
            if existing.input_digest != input_digest:
                raise AppError("Voiceover idempotency conflict", 409)
            return JobSubmitRead(
                job=ExecutionJobRead.model_validate(existing), reused=True
            )
        job = ExecutionJob(
            job_type=VOICEOVER_GENERATE_V1,
            source_type="video_composition",
            source_id=composition.id,
            input_digest=input_digest,
            idempotency_key=key,
            input_payload={
                "composition_id": composition.id,
                "script_version_id": version.id,
                "product_id": product_id,
                "narration_digest": data.narration_digest,
                "language": data.language,
                "voice": data.voice,
                "speaking_rate": data.speaking_rate,
                "target_duration_ms": target_duration_ms,
            },
            concurrency_key=f"voiceover-{composition.id}",
            estimated_cost=Decimal("0"),
            currency="USD",
            cost_confirmed=True,
            max_attempts=1,
            status="QUEUED",
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return JobSubmitRead(job=ExecutionJobRead.model_validate(job), reused=False)

    def generate(
        self,
        *,
        composition_id: int,
        script_version_id: int,
        narration_digest: str,
        language: str,
        voice: str,
        speaking_rate: float,
        target_duration_ms: int,
        provider: TtsProvider,
    ) -> VideoCompositionAudioArtifact:
        composition = self.session.get(VideoComposition, composition_id)
        version = self.session.get(VideoScriptVersion, script_version_id)
        if (
            composition is None
            or version is None
            or composition.duration_ms != target_duration_ms
        ):
            raise AppError("Voiceover source not found", 404)
        actual_digest = hashlib.sha256(version.full_narration.encode()).hexdigest()
        if actual_digest != narration_digest:
            raise AppError("Voiceover narration changed", 409)
        content = provider.generate(
            text=version.full_narration,
            language=language,
            voice=voice,
            rate=speaking_rate,
        )
        content, natural_duration_ms, duration_ms = self._normalize_wav(
            content, target_duration_ms
        )
        digest = hashlib.sha256(content).hexdigest()
        existing = (
            self.session.query(VideoCompositionAudioArtifact)
            .filter_by(composition_id=composition.id, kind="voiceover", sha256=digest)
            .one_or_none()
        )
        if existing is not None:
            return existing
        root = Path(self.settings.video_artifact_storage_root or "")
        if (
            not root.is_absolute()
            or len(content) > self.settings.video_artifact_max_bytes
        ):
            raise AppError("Artifact storage is not configured", 503)
        root.mkdir(parents=True, exist_ok=True)
        filename = f"voiceover-{composition.id}-{digest[:16]}.wav"
        destination = (root.resolve() / filename).resolve()
        if destination.parent != root.resolve():
            raise AppError("Voiceover storage path is unsafe", 500)
        handle, temporary = tempfile.mkstemp(
            prefix=f".{filename}.", suffix=".tmp", dir=root
        )
        created = False
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, destination)
                created = True
            except FileExistsError:
                if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                    raise AppError("Voiceover immutable conflict", 409) from None
        finally:
            Path(temporary).unlink(missing_ok=True)
        artifact = VideoCompositionAudioArtifact(
            product_id=composition.product_id,
            video_project_id=composition.video_project_id,
            composition_id=composition.id,
            kind="voiceover",
            storage_path=filename,
            content_type="audio/wav",
            size_bytes=len(content),
            sha256=digest,
            duration_ms=duration_ms,
            natural_duration_ms=natural_duration_ms,
        )
        self.session.add(artifact)
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            if created:
                destination.unlink(missing_ok=True)
            raise
        self.session.refresh(artifact)
        return artifact

    @staticmethod
    def _normalize_wav(
        content: bytes, target_duration_ms: int
    ) -> tuple[bytes, int, int]:
        try:
            with wave.open(io.BytesIO(content), "rb") as wav:
                if (
                    wav.getframerate() != 48000
                    or wav.getnchannels() != 2
                    or wav.getsampwidth() != 2
                ):
                    raise AppError("Voiceover WAV contract is invalid", 422)
                sample_rate = wav.getframerate()
                natural_frames = wav.getnframes()
                frame_size = wav.getnchannels() * wav.getsampwidth()
                speech = wav.readframes(natural_frames)
                compression = (wav.getcomptype(), wav.getcompname())
        except (wave.Error, EOFError) as exc:
            raise AppError("Voiceover WAV cannot be decoded", 422) from exc
        if natural_frames <= 0 or len(speech) != natural_frames * frame_size:
            raise AppError("Voiceover WAV contract is invalid", 422)
        target_frame_numerator = sample_rate * target_duration_ms
        if target_duration_ms <= 0 or target_frame_numerator % 1000:
            raise AppError("Voiceover target timeline is invalid", 422)
        target_frames = target_frame_numerator // 1000
        natural_duration_ms = round(natural_frames * 1000 / sample_rate)
        if natural_frames > target_frames:
            raise VoiceoverExceedsTimeline(natural_duration_ms, target_duration_ms)
        if natural_frames == target_frames:
            return content, natural_duration_ms, target_duration_ms
        silence = b"\x00" * ((target_frames - natural_frames) * frame_size)
        normalized = io.BytesIO()
        with wave.open(normalized, "wb") as output:
            output.setnchannels(2)
            output.setsampwidth(2)
            output.setframerate(sample_rate)
            output.setcomptype(*compression)
            output.writeframes(speech + silence)
        return normalized.getvalue(), natural_duration_ms, target_duration_ms

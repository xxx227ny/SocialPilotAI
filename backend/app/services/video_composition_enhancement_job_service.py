from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.execution.handlers.video_composition_enhancement import (
    VIDEO_COMPOSITION_ENHANCE_V1,
    VideoCompositionEnhanceV1Input,
)
from app.models import ExecutionJob, VideoCompositionEnhancement
from app.repositories.video_composition_enhancement import (
    VideoCompositionEnhancementRepository,
)
from app.schemas.execution import ExecutionJobRead
from app.schemas.video_composition_enhancement import (
    VideoCompositionEnhancementRead,
    VideoCompositionEnhancementSubmitRead,
    VideoCompositionEnhancementSubmitRequest,
)
from app.services.video_composition_enhancement_preflight import (
    VideoCompositionEnhancementPreflightService,
)


class VideoCompositionEnhancementJobService:
    def __init__(self, session: Session, settings) -> None:
        self.session = session
        self.settings = settings
        self.repository = VideoCompositionEnhancementRepository(session)

    def enqueue(
        self, product_id: int, data: VideoCompositionEnhancementSubmitRequest
    ) -> VideoCompositionEnhancementSubmitRead:
        if not self.settings.enable_video_composition_enhancement:
            raise AppError("Video composition enhancement is disabled", 503)
        expiry = data.preflight_expires_at.astimezone(UTC)
        if expiry <= datetime.now(UTC) + timedelta(seconds=5):
            raise AppError("Video composition enhancement Preflight has expired", 409)
        current = VideoCompositionEnhancementPreflightService(
            self.session, self.settings
        ).run(product_id, data, expires_at=expiry)
        if (
            current.input_digest != data.input_digest
            or current.source_chain_digest != data.source_chain_digest
            or current.preflight_digest != data.preflight_digest
            or not current.ready
        ):
            raise AppError("Video composition enhancement frozen input mismatch", 409)
        key = self._key(data.input_digest)
        existing = self.repository.get_by_key(key)
        if existing is not None:
            return self._reuse(existing, data.input_digest)
        parameters = current.parameters
        enhancement = VideoCompositionEnhancement(
            product_id=product_id,
            video_project_id=current.video_project_id,
            composition_id=current.composition_id,
            source_artifact_id=current.source_artifact_id,
            voiceover_artifact_id=current.voiceover.id,
            music_artifact_id=current.music.id if current.music else None,
            input_digest=current.input_digest,
            source_chain_digest=current.source_chain_digest,
            idempotency_key=key,
            subtitle_cues_json=[cue.model_dump(mode="json") for cue in current.cues],
            subtitle_style_json=current.style.model_dump(mode="json"),
            voiceover_gain_millidb=parameters.voiceover_gain_millidb,
            music_gain_millidb=parameters.music_gain_millidb,
            ducking_reduction_millidb=parameters.ducking_reduction_millidb,
            target_lufs_milli=parameters.target_lufs_milli,
            true_peak_millidb=parameters.true_peak_millidb,
            status="QUEUED",
        )
        self.session.add(enhancement)
        try:
            self.session.flush()
            payload = VideoCompositionEnhanceV1Input(
                enhancement_id=enhancement.id,
                product_id=enhancement.product_id,
                video_project_id=enhancement.video_project_id,
                composition_id=enhancement.composition_id,
                source_artifact_id=enhancement.source_artifact_id,
                voiceover_artifact_id=enhancement.voiceover_artifact_id,
                music_artifact_id=enhancement.music_artifact_id,
                frozen_input_digest=enhancement.input_digest,
                frozen_source_chain_digest=enhancement.source_chain_digest,
            )
            self.session.add(
                ExecutionJob(
                    job_type=VIDEO_COMPOSITION_ENHANCE_V1,
                    source_type="video_composition_enhancement",
                    source_id=enhancement.id,
                    input_digest=enhancement.input_digest,
                    idempotency_key=(
                        f"{VIDEO_COMPOSITION_ENHANCE_V1}:{enhancement.input_digest}"
                    ),
                    input_payload=payload.model_dump(mode="json"),
                    concurrency_key=f"video-composition-enhancement-{enhancement.id}",
                    estimated_cost=Decimal("0"),
                    currency="USD",
                    cost_confirmed=data.local_cpu_cost_confirmed,
                    max_attempts=1,
                    status="QUEUED",
                )
            )
            self.session.commit()
        except (IntegrityError, OperationalError) as error:
            self.session.rollback()
            concurrent = None
            for _ in range(5):
                concurrent = self.repository.get_by_key(key)
                if concurrent is not None:
                    break
                time.sleep(0.02)
            if concurrent is None:
                raise error
            return self._reuse(concurrent, data.input_digest)
        return self._read(enhancement.id, reused=False)

    def _reuse(
        self, enhancement: VideoCompositionEnhancement, digest: str
    ) -> VideoCompositionEnhancementSubmitRead:
        if enhancement.input_digest != digest:
            raise AppError("Enhancement idempotency input mismatch", 409)
        return self._read(enhancement.id, reused=True)

    def _read(
        self, enhancement_id: int, *, reused: bool
    ) -> VideoCompositionEnhancementSubmitRead:
        enhancement = self.repository.get(enhancement_id)
        job = (
            self.session.query(ExecutionJob)
            .filter_by(
                job_type=VIDEO_COMPOSITION_ENHANCE_V1,
                source_type="video_composition_enhancement",
                source_id=enhancement_id,
            )
            .one_or_none()
        )
        if enhancement is None or job is None:
            raise AppError("Enhancement queue record is incomplete", 409)
        return VideoCompositionEnhancementSubmitRead(
            enhancement=VideoCompositionEnhancementRead.model_validate(enhancement),
            job=ExecutionJobRead.model_validate(job),
            reused=reused,
        )

    @staticmethod
    def _key(digest: str) -> str:
        hashed = hashlib.sha256(digest.encode()).hexdigest()
        return f"video-composition-enhancement:{hashed}"

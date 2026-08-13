from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.execution.handlers.video_composition import (
    VIDEO_COMPOSITION_RENDER_V1,
    VideoCompositionRenderV1Input,
)
from app.models import ExecutionJob, VideoComposition, VideoCompositionShot
from app.repositories.video_composition import VideoCompositionRepository
from app.schemas.execution import ExecutionJobRead
from app.schemas.video_composition import (
    VideoCompositionRead,
    VideoCompositionSubmitRead,
    VideoCompositionSubmitRequest,
)
from app.services.video_composition_preflight import VideoCompositionPreflightService


class VideoCompositionJobService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.repository = VideoCompositionRepository(session)

    def enqueue(
        self, product_id: int, data: VideoCompositionSubmitRequest
    ) -> VideoCompositionSubmitRead:
        if not self.settings.enable_video_composition:
            raise AppError("Video composition execution is disabled", 503)
        expiry = data.preflight_expires_at.astimezone(UTC)
        if expiry <= datetime.now(UTC) + timedelta(seconds=5):
            raise AppError("Video composition Preflight has expired", 409)
        current = VideoCompositionPreflightService(self.session, self._storage()).run(
            product_id, data, expires_at=expiry
        )
        if (
            current.input_digest != data.input_digest
            or current.source_chain_digest != data.source_chain_digest
            or current.preflight_digest != data.preflight_digest
            or not current.ready
        ):
            raise AppError("Video composition frozen input mismatch", 409)
        key = self._key(data.input_digest)
        existing = self.repository.get_by_key(key)
        if existing is not None:
            return self._reuse(existing, data.input_digest)
        composition = VideoComposition(
            product_id=product_id,
            video_project_id=data.video_project_id,
            input_digest=data.input_digest,
            source_chain_digest=data.source_chain_digest,
            idempotency_key=key,
            version_number=1,
            status="QUEUED",
        )
        self.session.add(composition)
        try:
            self.session.flush()
            for shot in current.shots:
                self.session.add(
                    VideoCompositionShot(
                        composition_id=composition.id,
                        sequence=shot.sequence,
                        start_ms=shot.start_ms,
                        end_ms=shot.end_ms,
                        trim_start_ms=shot.trim_start_ms,
                        trim_end_ms=shot.trim_end_ms,
                        transition_type=shot.transition_type,
                        product_id=shot.product_id,
                        video_project_id=shot.video_project_id,
                        source_render_task_id=shot.render_task_id,
                        source_artifact_id=shot.artifact_id,
                        source_artifact_sha256=shot.artifact_sha256,
                    )
                )
            payload = VideoCompositionRenderV1Input(
                composition_id=composition.id,
                product_id=product_id,
                video_project_id=data.video_project_id,
                frozen_input_digest=data.input_digest,
                frozen_source_chain_digest=data.source_chain_digest,
            )
            self.session.add(
                ExecutionJob(
                    job_type=VIDEO_COMPOSITION_RENDER_V1,
                    source_type="video_composition",
                    source_id=composition.id,
                    input_digest=data.input_digest,
                    idempotency_key=f"{VIDEO_COMPOSITION_RENDER_V1}:{data.input_digest}",
                    input_payload=payload.model_dump(mode="json"),
                    concurrency_key=f"video-composition-{composition.id}",
                    estimated_cost=Decimal("0"),
                    currency="USD",
                    cost_confirmed=data.local_cpu_cost_confirmed,
                    max_attempts=2,
                    status="QUEUED",
                )
            )
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            concurrent = self.repository.get_by_key(key)
            if concurrent is None:
                raise
            return self._reuse(concurrent, data.input_digest)
        return self._read(composition.id, reused=False)

    def _reuse(
        self, composition: VideoComposition, digest: str
    ) -> VideoCompositionSubmitRead:
        if composition.input_digest != digest:
            raise AppError("Composition idempotency input mismatch", 409)
        return self._read(composition.id, reused=True)

    def _read(self, composition_id: int, *, reused: bool) -> VideoCompositionSubmitRead:
        composition = self.repository.get(composition_id)
        job = (
            self.session.query(ExecutionJob)
            .filter_by(
                job_type=VIDEO_COMPOSITION_RENDER_V1,
                source_type="video_composition",
                source_id=composition_id,
            )
            .one_or_none()
        )
        if composition is None or job is None:
            raise AppError("Composition queue record is incomplete", 409)
        return VideoCompositionSubmitRead(
            composition=VideoCompositionRead.model_validate(composition),
            job=ExecutionJobRead.model_validate(job),
            reused=reused,
        )

    @staticmethod
    def _key(digest: str) -> str:
        return f"video-composition:{hashlib.sha256(digest.encode()).hexdigest()}"

    def _storage(self):
        from pathlib import Path

        from app.services.video_artifact_storage import LocalVideoArtifactStorage

        return LocalVideoArtifactStorage(
            Path(self.settings.video_artifact_storage_root or ""),
            self.settings.video_artifact_max_bytes,
        )

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.execution.handlers.wanx_video_render import (
    WANX_VIDEO_RENDER_REFRESH_V1,
    WANX_VIDEO_RENDER_SUBMIT_V1,
    WanxVideoRenderRefreshV1Input,
    WanxVideoRenderSubmitV1Input,
)
from app.models import ExecutionJob
from app.schemas.execution import ExecutionJobCreate, ExecutionJobCreateRead
from app.schemas.video_render import (
    VideoRenderRefreshJobRequest,
    VideoRenderSubmitJobRequest,
)
from app.services.execution_queue_service import ExecutionQueueService
from app.services.video_render_preflight import (
    VideoRenderPreflightService,
    compute_video_render_task_digest,
)
from app.services.video_render_service import VideoRenderService

_EXPIRY_CLOCK_SKEW = timedelta(seconds=5)


class VideoRenderJobService:
    """Freeze safe render identities and create business-owned queue Jobs."""

    def __init__(
        self,
        session: Session,
        settings: Settings,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.now = now or (lambda: datetime.now(UTC))

    def enqueue_submit(
        self, video_project_id: int, data: VideoRenderSubmitJobRequest
    ) -> ExecutionJobCreateRead:
        idempotency_key = self._key(
            WANX_VIDEO_RENDER_SUBMIT_V1, data.input_digest
        )
        existing = self._existing(idempotency_key)
        if existing is not None:
            payload = existing.input_payload
            if (
                existing.source_id != video_project_id
                or payload.get("product_id") != data.product_id
                or payload.get("marketing_strategy_id")
                != data.marketing_strategy_id
                or payload.get("copy_matrix_id") != data.copy_matrix_id
            ):
                raise AppError("Video render Job identity mismatch", 409)
            return ExecutionJobCreateRead(
                job=ExecutionQueueService(self.session).get(existing.id),
                reused=True,
            )
        expires_at = data.preflight_expires_at.astimezone(UTC)
        if expires_at <= self.now().astimezone(UTC) + _EXPIRY_CLOCK_SKEW:
            raise AppError("Video render Preflight has expired", 409)
        current = VideoRenderPreflightService(
            self.session, self.settings
        ).run(video_project_id, expires_at=expires_at)
        if (
            current.video_project_id != video_project_id
            or current.product_id != data.product_id
            or current.marketing_strategy_id != data.marketing_strategy_id
            or current.copy_matrix_id != data.copy_matrix_id
        ):
            raise AppError("Video render Preflight identity mismatch", 409)
        if current.input_digest != data.input_digest:
            raise AppError("Video render frozen input has changed", 409)
        if current.preflight_digest != data.preflight_digest:
            raise AppError("Video render Preflight digest mismatch", 409)
        if not current.ready_for_execution:
            raise AppError("Video render Preflight is not ready", 409)

        payload = WanxVideoRenderSubmitV1Input(
            video_project_id=video_project_id,
            product_id=data.product_id,
            marketing_strategy_id=data.marketing_strategy_id,
            copy_matrix_id=data.copy_matrix_id,
            frozen_input_digest=data.input_digest,
            preflight_digest=data.preflight_digest,
            preflight_expires_at=expires_at,
        )
        return ExecutionQueueService(self.session).create(
            ExecutionJobCreate(
                job_type=WANX_VIDEO_RENDER_SUBMIT_V1,
                source_type="video_project",
                source_id=video_project_id,
                input_digest=data.input_digest,
                idempotency_key=idempotency_key,
                input_payload=payload.model_dump(mode="json"),
                concurrency_key=f"wanx-video-render-project-{video_project_id}",
                estimated_cost=Decimal("0"),
                currency="USD",
                cost_confirmed=data.cost_confirmed,
                max_attempts=1,
            )
        )

    def enqueue_refresh(
        self, task_id: int, data: VideoRenderRefreshJobRequest
    ) -> ExecutionJobCreateRead:
        task = VideoRenderService(self.session).get_render_task(task_id)
        if task.video_project_id != data.video_project_id:
            raise AppError("Video render task identity mismatch", 409)
        idempotency_key = self._key(
            WANX_VIDEO_RENDER_REFRESH_V1,
            f"{task.id}:{data.refresh_request_id}",
        )
        existing = self._existing(idempotency_key)
        if existing is not None:
            return ExecutionJobCreateRead(
                job=ExecutionQueueService(self.session).get(existing.id),
                reused=True,
            )
        if task.status not in {"SUBMITTED", "PENDING", "RUNNING"}:
            raise AppError("Video render task cannot be refreshed", 409)
        digest = compute_video_render_task_digest(
            self.session, task, self.settings
        )
        payload = WanxVideoRenderRefreshV1Input(
            video_project_id=data.video_project_id,
            video_render_task_id=task.id,
            frozen_task_digest=digest,
            refresh_request_id=data.refresh_request_id,
        )
        return ExecutionQueueService(self.session).create(
            ExecutionJobCreate(
                job_type=WANX_VIDEO_RENDER_REFRESH_V1,
                source_type="video_render_task",
                source_id=task.id,
                input_digest=digest,
                idempotency_key=idempotency_key,
                input_payload=payload.model_dump(mode="json"),
                concurrency_key=f"wanx-video-render-task-{task.id}",
                estimated_cost=Decimal("0"),
                currency="USD",
                cost_confirmed=True,
                max_attempts=1,
            )
        )

    @staticmethod
    def _key(job_type: str, material: str) -> str:
        digest = hashlib.sha256(f"{job_type}:{material}".encode()).hexdigest()
        return f"{job_type}:{digest}"

    def _existing(self, idempotency_key: str) -> ExecutionJob | None:
        return self.session.scalar(
            select(ExecutionJob).where(
                ExecutionJob.idempotency_key == idempotency_key
            )
        )

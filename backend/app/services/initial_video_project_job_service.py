from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.execution.handlers.qwen_video_project import (
    QWEN_VIDEO_PROJECT_GENERATE_V1,
    QwenVideoProjectGenerateV1Input,
)
from app.schemas.execution import ExecutionJobCreate, ExecutionJobCreateRead
from app.schemas.video import (
    InitialVideoProjectExecutionRequest,
    InitialVideoProjectSourceRequest,
)
from app.services.execution_queue_service import ExecutionQueueService
from app.services.initial_video_project_preflight import (
    InitialVideoProjectPreflightService,
)

_EXPIRY_CLOCK_SKEW = timedelta(seconds=5)


class InitialVideoProjectJobService:
    """Confirm one expiring Preflight and enqueue immutable video input."""

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

    def enqueue(
        self,
        product_id: int,
        data: InitialVideoProjectExecutionRequest,
    ) -> ExecutionJobCreateRead:
        if product_id != data.product_id:
            raise AppError("Initial VideoProject product identity mismatch", 409)
        expires_at = data.preflight_expires_at.astimezone(UTC)
        if expires_at <= self.now().astimezone(UTC) + _EXPIRY_CLOCK_SKEW:
            raise AppError("Initial VideoProject Preflight has expired", 409)

        source = InitialVideoProjectSourceRequest.model_validate(
            data.model_dump(
                include={
                    "strategy_id",
                    "copy_matrix_id",
                    "platform",
                    "duration_seconds",
                    "aspect_ratio",
                }
            )
        )
        current = InitialVideoProjectPreflightService(
            self.session, self.settings
        ).run(product_id, source, expires_at=expires_at)
        if (
            current.product_id != product_id
            or current.strategy_id != data.strategy_id
            or current.copy_matrix_id != data.copy_matrix_id
            or current.platform != data.platform
            or current.duration_seconds != data.duration_seconds
            or current.aspect_ratio != data.aspect_ratio
        ):
            raise AppError("Initial VideoProject Preflight identity mismatch", 409)
        if current.input_digest != data.input_digest:
            raise AppError("Initial VideoProject frozen input has changed", 409)
        if current.preflight_digest != data.preflight_digest:
            raise AppError("Initial VideoProject Preflight digest mismatch", 409)
        if not current.ready_for_execution:
            raise AppError("Initial VideoProject Preflight is not ready", 409)

        payload = QwenVideoProjectGenerateV1Input(
            product_id=product_id,
            marketing_strategy_id=data.strategy_id,
            copy_matrix_id=data.copy_matrix_id,
            platform=data.platform,
            duration_seconds=data.duration_seconds,
            aspect_ratio=data.aspect_ratio,
            frozen_input_digest=data.input_digest,
            preflight_digest=data.preflight_digest,
            preflight_expires_at=expires_at,
        )
        return ExecutionQueueService(self.session).create(
            ExecutionJobCreate(
                job_type=QWEN_VIDEO_PROJECT_GENERATE_V1,
                source_type="product",
                source_id=product_id,
                input_digest=data.input_digest,
                idempotency_key=self._idempotency_key(data.input_digest),
                input_payload=payload.model_dump(mode="json"),
                concurrency_key=f"qwen-video-project-product-{product_id}",
                estimated_cost=Decimal("0"),
                currency="USD",
                cost_confirmed=data.cost_confirmed,
                max_attempts=2,
            )
        )

    @staticmethod
    def _idempotency_key(input_digest: str) -> str:
        material = f"{QWEN_VIDEO_PROJECT_GENERATE_V1}:{input_digest}".encode()
        return (
            f"{QWEN_VIDEO_PROJECT_GENERATE_V1}:"
            f"{hashlib.sha256(material).hexdigest()}"
        )

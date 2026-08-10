from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.execution.handlers.qwen_copy_matrix import (
    QWEN_COPY_MATRIX_GENERATE_V1,
    QwenCopyMatrixGenerateV1Input,
)
from app.schemas.copy import CopyJobEnqueueRequest
from app.schemas.execution import ExecutionJobCreate, ExecutionJobCreateRead
from app.services.copy_preflight import CopyPreflightService
from app.services.execution_queue_service import ExecutionQueueService

_EXPIRY_CLOCK_SKEW = timedelta(seconds=5)


class CopyJobService:
    """Validate an expiring Copy preflight and enqueue stable input."""

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
        task_id: int,
        strategy_id: int,
        data: CopyJobEnqueueRequest,
    ) -> ExecutionJobCreateRead:
        if strategy_id != data.strategy_id:
            raise AppError("Copy strategy identity mismatch", 409)
        expires_at = data.preflight_expires_at.astimezone(UTC)
        if expires_at <= self.now().astimezone(UTC) + _EXPIRY_CLOCK_SKEW:
            raise AppError("Copy preflight has expired", 409)

        current = CopyPreflightService(self.session, self.settings).run(
            task_id, strategy_id, expires_at=expires_at
        )
        if (
            current.product_id != data.product_id
            or current.task_id != task_id
            or current.strategy_id != strategy_id
        ):
            raise AppError("Copy preflight identity mismatch", 409)
        if current.input_digest != data.input_digest:
            raise AppError("Copy frozen input has changed", 409)
        if current.preflight_digest != data.preflight_digest:
            raise AppError("Copy preflight digest mismatch", 409)
        if not current.ready_for_execution:
            raise AppError("Copy preflight is not ready", 409)

        payload = QwenCopyMatrixGenerateV1Input(
            product_id=current.product_id,
            marketing_brief_id=current.task_id,
            marketing_strategy_id=current.strategy_id,
            preflight_product_id=current.product_id,
            preflight_marketing_brief_id=current.task_id,
            preflight_marketing_strategy_id=current.strategy_id,
            frozen_digest=current.input_digest,
        )
        return ExecutionQueueService(self.session).create(
            ExecutionJobCreate(
                job_type=QWEN_COPY_MATRIX_GENERATE_V1,
                source_type="marketing_strategy",
                source_id=current.strategy_id,
                input_digest=current.input_digest,
                idempotency_key=self._idempotency_key(current.input_digest),
                input_payload=payload.model_dump(mode="json"),
                concurrency_key=f"qwen-copy-product-{current.product_id}",
                estimated_cost=Decimal("0"),
                currency="USD",
                cost_confirmed=data.cost_confirmed,
                max_attempts=2,
            )
        )

    @staticmethod
    def _idempotency_key(input_digest: str) -> str:
        material = f"{QWEN_COPY_MATRIX_GENERATE_V1}:{input_digest}".encode()
        return (
            f"{QWEN_COPY_MATRIX_GENERATE_V1}:"
            f"{hashlib.sha256(material).hexdigest()}"
        )

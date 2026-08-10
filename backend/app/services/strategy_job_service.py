from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.execution.handlers.qwen_strategy import (
    QWEN_STRATEGY_GENERATE_V1,
    QwenStrategyGenerateV1Input,
)
from app.schemas.execution import ExecutionJobCreate, ExecutionJobCreateRead
from app.schemas.strategy import StrategyJobEnqueueRequest
from app.services.execution_queue_service import ExecutionQueueService
from app.services.strategy_preflight import StrategyPreflightService

_EXPIRY_CLOCK_SKEW = timedelta(seconds=5)


class StrategyJobService:
    """Validate an expiring Strategy preflight and enqueue stable input."""

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
        self, task_id: int, data: StrategyJobEnqueueRequest
    ) -> ExecutionJobCreateRead:
        expires_at = data.preflight_expires_at.astimezone(UTC)
        if expires_at <= self.now().astimezone(UTC) + _EXPIRY_CLOCK_SKEW:
            raise AppError("Strategy preflight has expired", 409)

        current = StrategyPreflightService(self.session, self.settings).run(
            task_id, expires_at=expires_at
        )
        if current.product_id != data.product_id or current.task_id != task_id:
            raise AppError("Strategy preflight identity mismatch", 409)
        if current.input_digest != data.input_digest:
            raise AppError("Strategy frozen input has changed", 409)
        if current.preflight_digest != data.preflight_digest:
            raise AppError("Strategy preflight digest mismatch", 409)
        if not current.ready_for_execution:
            raise AppError("Strategy preflight is not ready", 409)

        payload = QwenStrategyGenerateV1Input(
            product_id=current.product_id,
            marketing_brief_id=current.task_id,
            preflight_product_id=current.product_id,
            preflight_marketing_brief_id=current.task_id,
            frozen_digest=current.input_digest,
        )
        idempotency_key = self._idempotency_key(current.input_digest)
        return ExecutionQueueService(self.session).create(
            ExecutionJobCreate(
                job_type=QWEN_STRATEGY_GENERATE_V1,
                source_type="marketing_brief",
                source_id=current.task_id,
                input_digest=current.input_digest,
                idempotency_key=idempotency_key,
                input_payload=payload.model_dump(mode="json"),
                concurrency_key=f"qwen-strategy-product-{current.product_id}",
                estimated_cost=Decimal("0"),
                currency="USD",
                cost_confirmed=data.cost_confirmed,
                max_attempts=2,
            )
        )

    @staticmethod
    def _idempotency_key(input_digest: str) -> str:
        material = f"{QWEN_STRATEGY_GENERATE_V1}:{input_digest}".encode()
        return (
            f"{QWEN_STRATEGY_GENERATE_V1}:"
            f"{hashlib.sha256(material).hexdigest()}"
        )

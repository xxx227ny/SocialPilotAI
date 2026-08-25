from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.execution.handlers.qwen_video_script import QWEN_VIDEO_SCRIPT_GENERATE_V1
from app.models.batch_video import BatchVideoJob, BatchVideoVariant
from app.models.execution import ExecutionJob
from app.schemas.execution import (
    ExecutionJobCreate,
    ExecutionJobCreateRead,
    ExecutionJobRead,
)
from app.schemas.video_script_version import (
    QwenScriptJobCreateRequest,
    QwenScriptJobInput,
    QwenScriptPreflightRequest,
)
from app.services.execution_queue_service import ExecutionQueueService
from app.services.qwen_video_script_preflight import (
    QwenVideoScriptPreflightService,
)

_EXPIRY_SKEW = timedelta(seconds=5)


class QwenVideoScriptJobService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def enqueue(
        self, variant_id: int, data: QwenScriptJobCreateRequest
    ) -> ExecutionJobCreateRead:
        job_key = self._job_key(variant_id, data.idempotency_key)
        existing = self._recover_existing(job_key, variant_id, data.frozen_input_digest)
        if existing is not None:
            return existing
        expires_at = data.preflight_expires_at
        if (
            expires_at.tzinfo is None
            or expires_at.astimezone(UTC) <= datetime.now(UTC) + _EXPIRY_SKEW
        ):
            raise AppError("Qwen script Preflight has expired", 409)
        request = QwenScriptPreflightRequest.model_validate(
            data.model_dump(
                include={
                    "idempotency_key",
                    "strategy_id",
                    "copy_matrix_id",
                    "parent_version_id",
                }
            )
        )
        checked = QwenVideoScriptPreflightService(self.session, self.settings).run(
            variant_id, request, expires_at=expires_at
        )
        if not checked.ready_for_execution:
            self.session.rollback()
            concurrent = self._recover_existing(
                job_key, variant_id, data.frozen_input_digest
            )
            if concurrent is not None:
                return concurrent
            raise AppError("Qwen script Preflight is not ready", 409)
        expected = (
            checked.frozen_input_digest,
            checked.preflight_digest,
            checked.estimated_cost_min,
            checked.estimated_cost_max,
            checked.currency,
            checked.cost_estimate_basis,
        )
        supplied = (
            data.frozen_input_digest,
            data.preflight_digest,
            data.estimated_cost_min,
            data.estimated_cost_max,
            data.currency.upper(),
            data.cost_estimate_basis,
        )
        if expected != supplied:
            raise AppError("Qwen script cost confirmation no longer matches", 409)
        queue = ExecutionQueueService(self.session)
        payload = QwenScriptJobInput(
            variant_id=variant_id,
            idempotency_key=data.idempotency_key,
            strategy_id=data.strategy_id,
            copy_matrix_id=data.copy_matrix_id,
            parent_version_id=data.parent_version_id,
            frozen_input_digest=data.frozen_input_digest,
            preflight_digest=data.preflight_digest,
            preflight_expires_at=expires_at,
            estimated_cost_min=data.estimated_cost_min,
            estimated_cost_max=data.estimated_cost_max,
            currency=data.currency.upper(),
            cost_estimate_basis=data.cost_estimate_basis,
            provider_model=checked.provider_model,
        )
        create = ExecutionJobCreate(
            job_type=QWEN_VIDEO_SCRIPT_GENERATE_V1,
            source_type="batch_video_variant",
            source_id=variant_id,
            input_digest=data.frozen_input_digest,
            idempotency_key=job_key,
            input_payload=payload.model_dump(mode="json"),
            concurrency_key=f"qwen-video-script-variant-{variant_id}",
            estimated_cost=data.estimated_cost_max,
            currency=data.currency.upper(),
            cost_confirmed=True,
            max_attempts=1,
        )
        variant = self.session.get(BatchVideoVariant, variant_id)
        if variant is None:
            raise AppError("Qwen script generation was not found", 404)
        reserved = self.session.scalar(
            update(BatchVideoJob)
            .where(
                BatchVideoJob.id == variant.batch_video_job_id,
                BatchVideoJob.qwen_script_calls_reserved
                < BatchVideoJob.qwen_script_call_quota,
            )
            .values(
                qwen_script_calls_reserved=BatchVideoJob.qwen_script_calls_reserved + 1
            )
            .returning(BatchVideoJob.qwen_script_calls_reserved)
        )
        if reserved is None:
            self.session.rollback()
            concurrent = self._recover_existing(
                job_key, variant_id, data.frozen_input_digest
            )
            if concurrent is not None:
                return concurrent
            raise AppError("Qwen script call quota is exhausted", 409)
        try:
            return queue.create(create)
        except Exception:
            self.session.rollback()
            raise

    def recover_exact_job(
        self,
        variant_id: int,
        client_key: str,
        input_digest: str,
    ) -> ExecutionJobCreateRead | None:
        """Read an existing exact job without reserving quota or creating work."""
        return self._recover_existing(
            self._job_key(variant_id, client_key),
            variant_id,
            input_digest,
        )

    @staticmethod
    def _job_key(variant_id: int, client_key: str) -> str:
        material = f"{variant_id}:{client_key}".encode()
        return f"{QWEN_VIDEO_SCRIPT_GENERATE_V1}:{hashlib.sha256(material).hexdigest()}"

    def _recover_existing(
        self, job_key: str, variant_id: int, input_digest: str
    ) -> ExecutionJobCreateRead | None:
        existing = self.session.scalar(
            select(ExecutionJob).where(ExecutionJob.idempotency_key == job_key)
        )
        if existing is None:
            return None
        if (
            existing.job_type != QWEN_VIDEO_SCRIPT_GENERATE_V1
            or existing.source_type != "batch_video_variant"
            or existing.source_id != variant_id
            or existing.input_digest != input_digest
        ):
            raise AppError("Idempotency key was used for different input", 409)
        return ExecutionJobCreateRead(
            job=ExecutionJobRead.model_validate(existing), reused=True
        )

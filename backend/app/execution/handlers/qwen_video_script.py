from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.execution.contracts import ExecutionContext, HandlerResult
from app.models import BatchVideoJob, BatchVideoVariant, ExecutionJob
from app.providers import TextGenerationProvider
from app.providers.base import ProviderError
from app.providers.live_configuration import get_provider_failure_metadata
from app.schemas.video_script_version import (
    QwenScriptJobInput,
    QwenScriptPreflightRequest,
)
from app.services.qwen_video_script_generation_service import (
    QwenVideoScriptGenerationService,
)
from app.services.qwen_video_script_preflight import (
    QwenVideoScriptPreflightService,
)
from app.services.video_script_version_service import VideoScriptVersionService

QWEN_VIDEO_SCRIPT_GENERATE_V1 = "qwen.video_script.generate.v1"


class _SessionFactory(Protocol):
    def __call__(self) -> Session: ...


class _ContextProvider(TextGenerationProvider):
    def __init__(
        self, context: ExecutionContext, provider: TextGenerationProvider
    ) -> None:
        self.context = context
        self.provider = provider

    def generate(self, prompt: str) -> str:
        self.context.before_provider_call(may_submit_external=True)
        return self.provider.generate(prompt)


class QwenVideoScriptGenerateV1Handler:
    job_type = QWEN_VIDEO_SCRIPT_GENERATE_V1
    input_schema = QwenScriptJobInput

    def __init__(
        self,
        *,
        session_factory: _SessionFactory,
        provider: TextGenerationProvider,
        settings: Settings,
    ) -> None:
        self.session_factory = session_factory
        self.provider = provider
        self.settings = settings

    def execute(self, context: ExecutionContext, payload: BaseModel) -> HandlerResult:
        data = QwenScriptJobInput.model_validate(payload)
        if (
            data.preflight_expires_at.tzinfo is None
            or data.preflight_expires_at.astimezone(UTC) <= datetime.now(UTC)
        ):
            return HandlerResult.failed("QWEN_SCRIPT_PREFLIGHT_EXPIRED")
        request = QwenScriptPreflightRequest(
            idempotency_key=data.idempotency_key,
            strategy_id=data.strategy_id,
            copy_matrix_id=data.copy_matrix_id,
            parent_version_id=data.parent_version_id,
        )
        with self.session_factory() as session:
            job = session.get(ExecutionJob, context.job_id)
            variant = session.get(BatchVideoVariant, data.variant_id)
            batch = (
                session.get(BatchVideoJob, variant.batch_video_job_id)
                if variant is not None
                else None
            )
            reserved_jobs = (
                session.scalar(
                    select(func.count(ExecutionJob.id))
                    .join(
                        BatchVideoVariant,
                        ExecutionJob.source_id == BatchVideoVariant.id,
                    )
                    .where(
                        ExecutionJob.job_type == QWEN_VIDEO_SCRIPT_GENERATE_V1,
                        ExecutionJob.source_type == "batch_video_variant",
                        BatchVideoVariant.batch_video_job_id == batch.id,
                    )
                )
                if batch is not None
                else 0
            )
            if (
                job is None
                or job.job_type != QWEN_VIDEO_SCRIPT_GENERATE_V1
                or job.source_type != "batch_video_variant"
                or job.source_id != data.variant_id
                or job.input_digest != data.frozen_input_digest
                or job.status != "RUNNING"
                or not job.cost_confirmed
                or job.estimated_cost != data.estimated_cost_max
                or job.currency != data.currency
                or job.max_attempts != 1
                or batch is None
                or batch.qwen_script_calls_reserved < 1
                or batch.qwen_script_calls_reserved != reserved_jobs
            ):
                return HandlerResult.failed("QWEN_SCRIPT_RESERVATION_INVALID")
            try:
                service = QwenVideoScriptPreflightService(session, self.settings)
                checked = service.run(
                    data.variant_id, request, expires_at=data.preflight_expires_at
                )
            except AppError:
                return HandlerResult.failed("QWEN_SCRIPT_PREFLIGHT_FAILED")
            if (
                checked.frozen_input_digest != data.frozen_input_digest
                or checked.preflight_digest != data.preflight_digest
                or checked.estimated_cost_min != data.estimated_cost_min
                or checked.estimated_cost_max != data.estimated_cost_max
                or checked.currency != data.currency
                or checked.cost_estimate_basis != data.cost_estimate_basis
                or checked.provider_model != data.provider_model
            ):
                return HandlerResult.failed("QWEN_SCRIPT_FROZEN_INPUT_CHANGED")
            prompt_snapshot = service.prompt_snapshot(checked)
            guarded = _ContextProvider(context, self.provider)
            try:
                generated = QwenVideoScriptGenerationService(guarded).generate(
                    prompt_snapshot
                )
            except ProviderError as error:
                metadata = get_provider_failure_metadata(error)
                if metadata is None:
                    return HandlerResult.submit_unknown(
                        "QWEN_SCRIPT_PROVIDER_RESULT_UNKNOWN", provider_name="qwen"
                    )
                details = {
                    "phase": metadata.phase,
                    "http_status": metadata.http_status,
                    "request_id_digest": metadata.request_id_digest,
                    "potentially_billable": metadata.potentially_billable,
                }
                safe = re.sub(
                    r"[^A-Z0-9_]", "_", (metadata.safe_error_code or "FAILED").upper()
                )
                code = f"QWEN_SCRIPT_{safe}"[:100]
                if metadata.uncertain:
                    return HandlerResult.submit_unknown(
                        code,
                        safe_error_details=details,
                        provider_name="qwen",
                    )
                outcome = (
                    "NOT_SUBMITTED"
                    if metadata.phase == "connect" and not metadata.potentially_billable
                    else "EXPLICIT_FAILURE"
                )
                return HandlerResult.failed(
                    code,
                    safe_error_details=details,
                    provider_submission_state=outcome,
                )
            except AppError:
                return HandlerResult.failed(
                    "QWEN_SCRIPT_INVALID_RESPONSE",
                    provider_submission_state="RESPONSE_RECEIVED",
                )
            try:
                version = VideoScriptVersionService(session).create_qwen_generated(
                    checked=checked,
                    output=generated.output,
                    execution_job_id=context.job_id,
                    prompt_snapshot=prompt_snapshot,
                    prompt_digest=generated.prompt_digest,
                    provider_response_digest=generated.provider_response_digest,
                )
            except AppError:
                return HandlerResult.failed(
                    "QWEN_SCRIPT_PERSISTENCE_REJECTED",
                    provider_submission_state="RESPONSE_RECEIVED",
                )
            return HandlerResult.succeeded(
                provider_name="qwen",
                result_entity_type="video_script_version",
                result_entity_id=version.id,
                provider_submission_state="RESPONSE_RECEIVED",
            )

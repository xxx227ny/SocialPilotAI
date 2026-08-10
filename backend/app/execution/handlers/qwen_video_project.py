from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.execution.contracts import ExecutionContext, HandlerResult
from app.providers import TextGenerationProvider
from app.schemas.video import InitialVideoProjectSourceRequest
from app.services.initial_video_project_generation_service import (
    InitialVideoProjectGenerationService,
)
from app.services.initial_video_project_preflight import (
    InitialVideoProjectPreflightService,
)

QWEN_VIDEO_PROJECT_GENERATE_V1 = "qwen.video_project.generate.v1"


class _SessionFactory(Protocol):
    def __call__(self) -> Session: ...


class QwenVideoProjectGenerateV1Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: int = Field(gt=0)
    marketing_strategy_id: int = Field(gt=0)
    copy_matrix_id: int = Field(gt=0)
    platform: Literal["TikTok", "Instagram", "Facebook"]
    duration_seconds: Literal[15, 30]
    aspect_ratio: Literal["9:16"]
    frozen_input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_expires_at: datetime

    @field_validator("preflight_expires_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("preflight_expires_at must include a timezone")
        return value


class _ContextTextProvider(TextGenerationProvider):
    def __init__(
        self, context: ExecutionContext, provider: TextGenerationProvider
    ) -> None:
        self.context = context
        self.provider = provider

    def generate(self, prompt: str) -> str:
        self.context.before_provider_call(may_submit_external=True)
        return self.provider.generate(prompt)


class QwenVideoProjectGenerateV1Handler:
    job_type = QWEN_VIDEO_PROJECT_GENERATE_V1
    input_schema = QwenVideoProjectGenerateV1Input

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

    def execute(
        self, context: ExecutionContext, payload: BaseModel
    ) -> HandlerResult:
        data = QwenVideoProjectGenerateV1Input.model_validate(payload)
        source = InitialVideoProjectSourceRequest(
            strategy_id=data.marketing_strategy_id,
            copy_matrix_id=data.copy_matrix_id,
            platform=data.platform,
            duration_seconds=data.duration_seconds,
            aspect_ratio=data.aspect_ratio,
        )
        with self.session_factory() as session:
            try:
                preflight = InitialVideoProjectPreflightService(
                    session, self.settings
                ).run(
                    data.product_id,
                    source,
                    expires_at=data.preflight_expires_at,
                )
            except AppError:
                return HandlerResult.failed("VIDEO_PROJECT_PREFLIGHT_FAILED")
            if (
                preflight.product_id != data.product_id
                or preflight.strategy_id != data.marketing_strategy_id
                or preflight.copy_matrix_id != data.copy_matrix_id
            ):
                return HandlerResult.failed(
                    "VIDEO_PROJECT_PREFLIGHT_IDENTITY_MISMATCH"
                )
            if preflight.input_digest != data.frozen_input_digest:
                return HandlerResult.failed(
                    "VIDEO_PROJECT_FROZEN_DIGEST_MISMATCH"
                )
            if preflight.preflight_digest != data.preflight_digest:
                return HandlerResult.failed(
                    "VIDEO_PROJECT_PREFLIGHT_DIGEST_MISMATCH"
                )
            if not preflight.ready_for_execution:
                return HandlerResult.failed("VIDEO_PROJECT_PREFLIGHT_NOT_READY")

            guarded_provider = _ContextTextProvider(context, self.provider)
            try:
                result = InitialVideoProjectGenerationService(
                    session, guarded_provider, self.settings
                ).generate_frozen(
                    data.product_id,
                    source,
                    preflight_digest=data.preflight_digest,
                )
            except AppError:
                if context.provider_state()[1]:
                    raise
                return HandlerResult.failed("VIDEO_PROJECT_EXECUTION_REJECTED")
            return HandlerResult.succeeded(
                provider_name="qwen",
                result_entity_type="video_project",
                result_entity_id=result.generated_video_project.id,
            )

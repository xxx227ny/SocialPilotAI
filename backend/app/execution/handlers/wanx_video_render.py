from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.execution.contracts import ExecutionContext, HandlerResult
from app.models import ProductAsset
from app.providers.visual_base import (
    VisualGenerationProvider,
    VisualGenerationRequest,
    VisualReferenceImage,
    VisualTaskSnapshot,
    VisualTaskSubmission,
)
from app.services.product_asset_storage import ProductAssetStorage
from app.services.video_artifact_storage import (
    ProviderOutputFetcher,
    VideoArtifactStorage,
)
from app.services.video_render_execution_service import (
    VideoRenderExecutionService,
)
from app.services.video_render_operation_service import (
    VideoProjectRenderExecutionService,
)
from app.services.video_render_preflight import (
    VideoRenderPreflightService,
    compute_video_render_task_digest,
)
from app.services.video_render_service import VideoRenderService

WANX_VIDEO_RENDER_SUBMIT_V1 = "wanx.video_render.submit.v1"
WANX_VIDEO_RENDER_REFRESH_V1 = "wanx.video_render.refresh.v1"


class _SessionFactory(Protocol):
    def __call__(self) -> Session: ...


class WanxVideoRenderSubmitV1Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    video_project_id: int = Field(gt=0)
    product_id: int = Field(gt=0)
    marketing_strategy_id: int = Field(gt=0)
    copy_matrix_id: int | None = Field(default=None, gt=0)
    frozen_input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_expires_at: datetime
    render_mode: str = Field(pattern=r"^(scene|product_reference)$")
    reference_product_asset_id: int | None = Field(default=None, gt=0)
    reference_product_asset_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )

    @field_validator("preflight_expires_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("preflight_expires_at must include a timezone")
        return value


class WanxVideoRenderRefreshV1Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    video_project_id: int = Field(gt=0)
    video_render_task_id: int = Field(gt=0)
    frozen_task_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    refresh_request_id: str = Field(min_length=16, max_length=128)


class _ContextVisualProvider(VisualGenerationProvider):
    def __init__(
        self,
        context: ExecutionContext,
        provider: VisualGenerationProvider,
    ) -> None:
        self.context = context
        self.provider = provider

    async def submit(self, request: VisualGenerationRequest) -> VisualTaskSubmission:
        self.context.before_provider_call(may_submit_external=True)
        return await self.provider.submit(request)

    async def fetch(self, provider_task_id: str) -> VisualTaskSnapshot:
        self.context.before_provider_call(may_submit_external=False)
        return await self.provider.fetch(provider_task_id)


class WanxVideoRenderSubmitV1Handler:
    job_type = WANX_VIDEO_RENDER_SUBMIT_V1
    input_schema = WanxVideoRenderSubmitV1Input

    def __init__(
        self,
        *,
        session_factory: _SessionFactory,
        provider: VisualGenerationProvider,
        settings: Settings,
        output_fetcher: ProviderOutputFetcher,
        artifact_storage: VideoArtifactStorage,
    ) -> None:
        self.session_factory = session_factory
        self.provider = provider
        self.settings = settings
        self.output_fetcher = output_fetcher
        self.artifact_storage = artifact_storage

    def execute(self, context: ExecutionContext, payload: BaseModel) -> HandlerResult:
        data = WanxVideoRenderSubmitV1Input.model_validate(payload)
        with self.session_factory() as session:
            try:
                preflight = VideoRenderPreflightService(session, self.settings).run(
                    data.video_project_id,
                    expires_at=data.preflight_expires_at,
                )
            except AppError:
                return HandlerResult.failed("VIDEO_RENDER_PREFLIGHT_FAILED")
            if (
                preflight.product_id != data.product_id
                or preflight.marketing_strategy_id != data.marketing_strategy_id
                or preflight.copy_matrix_id != data.copy_matrix_id
            ):
                return HandlerResult.failed("VIDEO_RENDER_IDENTITY_MISMATCH")
            if preflight.input_digest != data.frozen_input_digest:
                return HandlerResult.failed("VIDEO_RENDER_FROZEN_DIGEST_MISMATCH")
            if preflight.preflight_digest != data.preflight_digest:
                return HandlerResult.failed("VIDEO_RENDER_PREFLIGHT_DIGEST_MISMATCH")
            if not preflight.ready_for_execution:
                return HandlerResult.failed("VIDEO_RENDER_PREFLIGHT_NOT_READY")
            guarded = _ContextVisualProvider(context, self.provider)
            try:
                reference_image = self._reference_image(session, data)
                result = asyncio.run(
                    VideoProjectRenderExecutionService(
                        session,
                        guarded,
                        self.settings,
                        self.output_fetcher,
                        self.artifact_storage,
                    ).execute(
                        data.video_project_id,
                        reference_image=reference_image,
                        reference_product_asset_id=(data.reference_product_asset_id),
                        reference_product_asset_sha256=(
                            data.reference_product_asset_sha256
                        ),
                        whole_timeline=data.render_mode == "product_reference",
                    )
                )
            except AppError:
                if context.provider_state()[1]:
                    raise
                return HandlerResult.failed("VIDEO_RENDER_SUBMIT_REJECTED")
            return HandlerResult.succeeded(
                provider_name="wanx",
                result_entity_type="video_render_task",
                result_entity_id=result.task.id,
            )

    def _reference_image(
        self,
        session: Session,
        data: WanxVideoRenderSubmitV1Input,
    ) -> VisualReferenceImage | None:
        if data.render_mode == "scene":
            return None
        asset = session.get(ProductAsset, data.reference_product_asset_id)
        if (
            asset is None
            or asset.product_id != data.product_id
            or asset.sha256 != data.reference_product_asset_sha256
            or not asset.storage_identity
            or asset.content_type not in {"image/png", "image/jpeg", "image/webp"}
        ):
            raise AppError("Product reference image was not found", 404)
        storage = ProductAssetStorage(
            Path(self.settings.product_asset_storage_root or ""),
            self.settings.product_asset_max_bytes,
        )
        path = storage.resolve(asset.storage_identity, asset.sha256)
        return VisualReferenceImage(
            content=path.read_bytes(),
            content_type=asset.content_type,
        )


class WanxVideoRenderRefreshV1Handler:
    job_type = WANX_VIDEO_RENDER_REFRESH_V1
    input_schema = WanxVideoRenderRefreshV1Input

    def __init__(
        self,
        *,
        session_factory: _SessionFactory,
        provider: VisualGenerationProvider,
        settings: Settings,
        output_fetcher: ProviderOutputFetcher,
        artifact_storage: VideoArtifactStorage,
    ) -> None:
        self.session_factory = session_factory
        self.provider = provider
        self.settings = settings
        self.output_fetcher = output_fetcher
        self.artifact_storage = artifact_storage

    def execute(self, context: ExecutionContext, payload: BaseModel) -> HandlerResult:
        data = WanxVideoRenderRefreshV1Input.model_validate(payload)
        with self.session_factory() as session:
            try:
                task = VideoRenderService(session).get_render_task(
                    data.video_render_task_id
                )
                if task.video_project_id != data.video_project_id:
                    return HandlerResult.failed("VIDEO_RENDER_IDENTITY_MISMATCH")
                if (
                    compute_video_render_task_digest(session, task, self.settings)
                    != data.frozen_task_digest
                ):
                    return HandlerResult.failed("VIDEO_RENDER_FROZEN_DIGEST_MISMATCH")
                result = asyncio.run(
                    VideoRenderExecutionService(
                        session,
                        _ContextVisualProvider(context, self.provider),
                        self.settings,
                        output_fetcher=self.output_fetcher,
                        artifact_storage=self.artifact_storage,
                    ).refresh(task.id)
                )
            except AppError:
                return HandlerResult.failed("VIDEO_RENDER_REFRESH_REJECTED")
            entity_type = (
                "video_render_artifact"
                if result.artifact is not None
                else "video_render_task"
            )
            entity_id = (
                result.artifact.id if result.artifact is not None else result.task.id
            )
            return HandlerResult.succeeded(
                provider_name="wanx",
                result_entity_type=entity_type,
                result_entity_id=entity_id,
            )

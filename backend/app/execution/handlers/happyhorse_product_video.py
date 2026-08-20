from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.execution.contracts import ExecutionContext, HandlerResult
from app.models import ProductAsset, VideoProject, VideoRenderTask
from app.providers.visual_base import (
    VisualGenerationProvider,
    VisualGenerationRequest,
    VisualReferenceImage,
    VisualTaskSnapshot,
    VisualTaskSubmission,
)
from app.repositories.video_render import VideoRenderTaskRepository
from app.schemas.product_marketing_video import (
    HappyHorseReferenceImage,
    HappyHorseVideoPreflightRequest,
)
from app.services.product_asset_storage import ProductAssetStorage
from app.services.video_artifact_storage import (
    ProviderOutputFetcher,
    VideoArtifactStorage,
)
from app.services.video_render_execution_service import VideoRenderExecutionService

HAPPYHORSE_PRODUCT_VIDEO_SUBMIT_V1 = "happyhorse.product_video.submit.v1"
HAPPYHORSE_PRODUCT_VIDEO_REFRESH_V1 = "happyhorse.product_video.refresh.v1"


class _SessionFactory(Protocol):
    def __call__(self) -> Session: ...


class HappyHorseProductVideoSubmitV1Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: int = Field(gt=0)
    video_project_id: int = Field(gt=0)
    script_version_id: int = Field(gt=0)
    reference_images: list[HappyHorseReferenceImage] = Field(min_length=1, max_length=9)
    frozen_input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_expires_at: datetime

    @field_validator("preflight_expires_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("preflight_expires_at must include a timezone")
        return value


class HappyHorseProductVideoRefreshV1Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: int = Field(gt=0)
    video_project_id: int = Field(gt=0)
    video_render_task_id: int = Field(gt=0)
    frozen_task_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    refresh_request_id: str = Field(min_length=16, max_length=128)


class _ContextProvider(VisualGenerationProvider):
    def __init__(
        self, context: ExecutionContext, provider: VisualGenerationProvider
    ) -> None:
        self.context = context
        self.provider = provider

    async def submit(self, request: VisualGenerationRequest) -> VisualTaskSubmission:
        self.context.before_provider_call(may_submit_external=True)
        return await self.provider.submit(request)

    async def fetch(self, provider_task_id: str) -> VisualTaskSnapshot:
        self.context.before_provider_call(may_submit_external=False)
        return await self.provider.fetch(provider_task_id)


class HappyHorseProductVideoSubmitV1Handler:
    job_type = HAPPYHORSE_PRODUCT_VIDEO_SUBMIT_V1
    input_schema = HappyHorseProductVideoSubmitV1Input

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
        from app.services.happyhorse_product_video_service import (
            HappyHorseProductVideoService,
        )

        data = HappyHorseProductVideoSubmitV1Input.model_validate(payload)
        with self.session_factory() as session:
            try:
                current = HappyHorseProductVideoService(
                    session, self.settings
                ).preflight(
                    data.product_id,
                    HappyHorseVideoPreflightRequest(
                        video_project_id=data.video_project_id,
                        script_version_id=data.script_version_id,
                        reference_images=data.reference_images,
                    ),
                    expires_at=data.preflight_expires_at,
                )
                if (
                    not current.ready
                    or current.input_digest != data.frozen_input_digest
                    or current.preflight_digest != data.preflight_digest
                ):
                    return HandlerResult.failed("HAPPYHORSE_FROZEN_INPUT_MISMATCH")
                task = self._create_task(session, data, current.input_digest)
                references = self._load_references(session, data)
                request = VisualGenerationRequest(
                    prompt=task.render_prompt,
                    duration_seconds=15,
                    aspect_ratio="9:16",
                    resolution="720P",
                    reference_images=references,
                )
                result = asyncio.run(
                    VideoRenderExecutionService(
                        session,
                        _ContextProvider(context, self.provider),
                        self.settings,
                        output_fetcher=self.output_fetcher,
                        artifact_storage=self.artifact_storage,
                        provider_name="happyhorse",
                        provider_label="HappyHorse",
                    ).submit(task.id, request)
                )
            except AppError:
                if context.provider_state()[1]:
                    raise
                return HandlerResult.failed("HAPPYHORSE_SUBMIT_REJECTED")
            return HandlerResult.succeeded(
                provider_name="happyhorse",
                result_entity_type="video_render_task",
                result_entity_id=result.task.id,
            )

    def _create_task(
        self,
        session: Session,
        data: HappyHorseProductVideoSubmitV1Input,
        input_digest: str,
    ) -> VideoRenderTask:
        project = session.get(VideoProject, data.video_project_id)
        if project is None:
            raise AppError("HappyHorse video source not found", 404)
        repository = VideoRenderTaskRepository(session)
        key = f"happyhorse-r2v:{input_digest}"
        existing = repository.get_by_idempotency_key(key)
        if existing is not None:
            if existing.video_project_id != project.id:
                raise AppError("HappyHorse render identity mismatch", 409)
            return existing
        from app.services.happyhorse_product_video_service import (
            HappyHorseProductVideoService,
        )

        prompt = HappyHorseProductVideoService._prompt(project)
        try:
            return repository.create(
                video_project_id=project.id,
                scene_sequence=1,
                render_prompt=prompt,
                duration_seconds=15,
                aspect_ratio="9:16",
                resolution="720P",
                idempotency_key=key,
            )
        except IntegrityError:
            session.rollback()
            existing = repository.get_by_idempotency_key(key)
            if existing is None:
                raise
            return existing

    def _load_references(
        self, session: Session, data: HappyHorseProductVideoSubmitV1Input
    ) -> tuple[VisualReferenceImage, ...]:
        storage = ProductAssetStorage(
            Path(self.settings.product_asset_storage_root or ""),
            self.settings.product_asset_max_bytes,
            ffmpeg_path=self.settings.video_composition_ffmpeg_path,
            ffprobe_path=self.settings.video_composition_ffprobe_path,
            process_timeout=self.settings.video_composition_process_timeout,
        )
        loaded: list[VisualReferenceImage] = []
        for reference in data.reference_images:
            asset = session.get(ProductAsset, reference.product_asset_id)
            if (
                asset is None
                or asset.product_id != data.product_id
                or asset.sha256 != reference.product_asset_sha256
                or not asset.storage_identity
                or asset.content_type not in {"image/png", "image/jpeg", "image/webp"}
            ):
                raise AppError("HappyHorse reference image identity is invalid", 409)
            path = storage.resolve(asset.storage_identity, asset.sha256)
            loaded.append(
                VisualReferenceImage(
                    content=path.read_bytes(), content_type=asset.content_type
                )
            )
        return tuple(loaded)


class HappyHorseProductVideoRefreshV1Handler:
    job_type = HAPPYHORSE_PRODUCT_VIDEO_REFRESH_V1
    input_schema = HappyHorseProductVideoRefreshV1Input

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
        from app.services.happyhorse_product_video_service import (
            happyhorse_task_digest,
        )

        data = HappyHorseProductVideoRefreshV1Input.model_validate(payload)
        with self.session_factory() as session:
            task = session.get(VideoRenderTask, data.video_render_task_id)
            if (
                task is None
                or task.video_project_id != data.video_project_id
                or task.provider_name != "happyhorse"
                or happyhorse_task_digest(task) != data.frozen_task_digest
            ):
                return HandlerResult.failed("HAPPYHORSE_FROZEN_TASK_MISMATCH")
            try:
                result = asyncio.run(
                    VideoRenderExecutionService(
                        session,
                        _ContextProvider(context, self.provider),
                        self.settings,
                        output_fetcher=self.output_fetcher,
                        artifact_storage=self.artifact_storage,
                        provider_name="happyhorse",
                        provider_label="HappyHorse",
                    ).refresh(task.id)
                )
            except AppError:
                return HandlerResult.failed("HAPPYHORSE_REFRESH_REJECTED")
            return HandlerResult.succeeded(
                provider_name="happyhorse",
                result_entity_type=(
                    "video_render_artifact"
                    if result.artifact is not None
                    else "video_render_task"
                ),
                result_entity_id=(
                    result.artifact.id
                    if result.artifact is not None
                    else result.task.id
                ),
            )

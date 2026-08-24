from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.execution.handlers.happyhorse_product_video import (
    HAPPYHORSE_PRODUCT_VIDEO_REFRESH_V1,
    HAPPYHORSE_PRODUCT_VIDEO_SUBMIT_V1,
    HappyHorseProductVideoRefreshV1Input,
    HappyHorseProductVideoSubmitV1Input,
)
from app.models import ExecutionJob, ProductAsset, VideoProject, VideoRenderTask
from app.providers.happyhorse_provider import (
    HAPPYHORSE_MODEL,
    TOKEN_PLAN_VIDEO_ENDPOINT,
)
from app.providers.live_configuration import effective_qwen_api_key
from app.schemas.execution import ExecutionJobCreate
from app.schemas.product_marketing_video import (
    HappyHorseReferenceImage,
    HappyHorseVideoPreflightRead,
    HappyHorseVideoPreflightRequest,
    HappyHorseVideoRefreshRequest,
    HappyHorseVideoSubmitRequest,
    JobSubmitRead,
)
from app.services.execution_queue_service import ExecutionQueueService

PREFLIGHT_TTL = timedelta(minutes=10)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def happyhorse_task_digest(task: VideoRenderTask) -> str:
    return _digest(
        {
            "id": task.id,
            "video_project_id": task.video_project_id,
            "render_prompt": task.render_prompt,
            "duration_seconds": task.duration_seconds,
            "aspect_ratio": task.aspect_ratio,
            "resolution": task.resolution,
            "provider_name": task.provider_name,
            "provider_task_id": task.provider_task_id,
        }
    )


class HappyHorseProductVideoService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def preflight(
        self,
        product_id: int,
        data: HappyHorseVideoPreflightRequest,
        *,
        expires_at: datetime | None = None,
    ) -> HappyHorseVideoPreflightRead:
        project = self.session.get(VideoProject, data.video_project_id)
        if (
            project is None
            or project.product_id != product_id
            or project.source_script_version_id != data.script_version_id
        ):
            raise AppError("HappyHorse video source not found", 404)
        if project.duration_seconds != 15 or project.aspect_ratio != "9:16":
            raise AppError("HappyHorse requires an exact 15-second 9:16 project", 409)
        references = self._validate_references(product_id, data.reference_images)
        missing: list[str] = []
        if not self.settings.enable_happyhorse_product_video:
            missing.append("happyhorse_execution_disabled")
        if not effective_qwen_api_key(self.settings):
            missing.append("token_plan_credentials")
        if self.settings.happyhorse_endpoint.rstrip("/") != TOKEN_PLAN_VIDEO_ENDPOINT:
            missing.append("happyhorse_endpoint")
        if self.settings.happyhorse_model != HAPPYHORSE_MODEL:
            missing.append("happyhorse_model")
        if not (self.settings.product_asset_storage_root or "").strip():
            missing.append("product_asset_storage")
        if not (self.settings.video_artifact_storage_root or "").strip():
            missing.append("video_artifact_storage")
        material = {
            "contract": "happyhorse-product-video-r2v-v1",
            "product_id": product_id,
            "video_project_id": project.id,
            "script_version_id": data.script_version_id,
            "script_content_digest": project.source_script_content_digest,
            "reference_images": [item.model_dump() for item in references],
            "prompt": self._prompt(project),
            "model": self.settings.happyhorse_model,
            "duration_seconds": 15,
            "aspect_ratio": "9:16",
            "resolution": "720P",
        }
        input_digest = _digest(material)
        expiry = (expires_at or datetime.now(UTC) + PREFLIGHT_TTL).astimezone(UTC)
        preflight_digest = _digest(
            {"input_digest": input_digest, "expires_at": expiry.isoformat()}
        )
        return HappyHorseVideoPreflightRead(
            **data.model_dump(),
            input_digest=input_digest,
            preflight_digest=preflight_digest,
            expires_at=expiry,
            provider_model=self.settings.happyhorse_model,
            estimated_cost=str(self.settings.happyhorse_estimated_cost),
            ready=not missing,
            missing_requirements=missing,
        )

    def enqueue_submit(
        self, product_id: int, data: HappyHorseVideoSubmitRequest
    ) -> JobSubmitRead:
        if not data.cost_confirmed:
            raise AppError("HappyHorse generation cost confirmation is required", 422)
        expires_at = data.preflight_expires_at.astimezone(UTC)
        current = self.preflight(
            product_id,
            HappyHorseVideoPreflightRequest(
                video_project_id=data.video_project_id,
                script_version_id=data.script_version_id,
                reference_images=data.reference_images,
            ),
            expires_at=expires_at,
        )
        if expires_at <= datetime.now(UTC) or not current.ready:
            raise AppError("HappyHorse video Preflight is not ready", 409)
        if (
            current.input_digest != data.input_digest
            or current.preflight_digest != data.preflight_digest
        ):
            raise AppError("HappyHorse frozen input has changed", 409)
        key = f"{HAPPYHORSE_PRODUCT_VIDEO_SUBMIT_V1}:{data.input_digest}"
        existing = self._existing(key)
        if existing is not None:
            if existing.input_digest != data.input_digest:
                raise AppError("HappyHorse Job identity mismatch", 409)
            return JobSubmitRead(
                job=ExecutionQueueService(self.session).get(existing.id), reused=True
            )
        payload = HappyHorseProductVideoSubmitV1Input(
            product_id=product_id,
            video_project_id=data.video_project_id,
            script_version_id=data.script_version_id,
            reference_images=data.reference_images,
            frozen_input_digest=data.input_digest,
            preflight_digest=data.preflight_digest,
            preflight_expires_at=expires_at,
        )
        created = ExecutionQueueService(self.session).create(
            ExecutionJobCreate(
                job_type=HAPPYHORSE_PRODUCT_VIDEO_SUBMIT_V1,
                source_type="video_project",
                source_id=data.video_project_id,
                input_digest=data.input_digest,
                idempotency_key=key,
                input_payload=payload.model_dump(mode="json"),
                concurrency_key=f"happyhorse-project-{data.video_project_id}",
                estimated_cost=self.settings.happyhorse_estimated_cost,
                currency="CNY",
                cost_confirmed=True,
                max_attempts=1,
            )
        )
        return JobSubmitRead(job=created.job, reused=created.reused)

    def enqueue_refresh(
        self,
        product_id: int,
        task_id: int,
        data: HappyHorseVideoRefreshRequest,
    ) -> JobSubmitRead:
        task = self.session.get(VideoRenderTask, task_id)
        project = self.session.get(VideoProject, data.video_project_id)
        if (
            task is None
            or project is None
            or project.product_id != product_id
            or task.video_project_id != project.id
            or task.provider_name != "happyhorse"
        ):
            raise AppError("HappyHorse render task not found", 404)
        if task.status not in {"SUBMITTED", "PENDING", "RUNNING"}:
            raise AppError("HappyHorse render task cannot be refreshed", 409)
        digest = happyhorse_task_digest(task)
        key = (
            f"{HAPPYHORSE_PRODUCT_VIDEO_REFRESH_V1}:{task.id}:{data.refresh_request_id}"
        )
        existing = self._existing(key)
        if existing is not None:
            return JobSubmitRead(
                job=ExecutionQueueService(self.session).get(existing.id), reused=True
            )
        payload = HappyHorseProductVideoRefreshV1Input(
            product_id=product_id,
            video_project_id=project.id,
            video_render_task_id=task.id,
            frozen_task_digest=digest,
            refresh_request_id=data.refresh_request_id,
        )
        created = ExecutionQueueService(self.session).create(
            ExecutionJobCreate(
                job_type=HAPPYHORSE_PRODUCT_VIDEO_REFRESH_V1,
                source_type="video_render_task",
                source_id=task.id,
                input_digest=digest,
                idempotency_key=key,
                input_payload=payload.model_dump(mode="json"),
                concurrency_key=f"happyhorse-task-{task.id}",
                estimated_cost=0,
                currency="CNY",
                cost_confirmed=True,
                max_attempts=1,
            )
        )
        return JobSubmitRead(job=created.job, reused=created.reused)

    def _validate_references(
        self, product_id: int, references: list[HappyHorseReferenceImage]
    ) -> list[HappyHorseReferenceImage]:
        if len({item.product_asset_id for item in references}) != len(references):
            raise AppError("HappyHorse reference images must be unique", 422)
        for item in references:
            asset = self.session.get(ProductAsset, item.product_asset_id)
            if (
                asset is None
                or asset.product_id != product_id
                or asset.sha256 != item.product_asset_sha256
                or not asset.storage_identity
                or asset.content_type not in {"image/png", "image/jpeg", "image/webp"}
            ):
                raise AppError("HappyHorse reference image identity is invalid", 409)
        return references

    @staticmethod
    def _prompt(project: VideoProject) -> str:
        scenes = " ".join(
            f"Scene {scene.get('sequence')}: {scene.get('visual_description')}; "
            f"action: {scene.get('action')}"
            for scene in project.scenes
        )
        return (
            f"Create a polished vertical product advertisement titled "
            f"'{project.title}'. Concept: {project.concept}. {scenes}. "
            f"End with this call to action: {project.cta}. Use the supplied "
            "reference images to keep the exact same product identity in every "
            "shot. Visibly demonstrate the scripted product operation and benefits, "
            "rather than showing only a static rotating hero shot. Brief hands may "
            "safely interact with the product only in ways supported by its category, "
            "script, and reference images, but show no faces or full bodies. Keep all "
            "safety covers and guards shown in the reference secured during operation. "
            "Never expose hazardous internals, depict direct human contact with active "
            "mechanisms, or invent unsupported capabilities. Use smooth cinematic "
            "motion and coherent commercial lighting. Preserve existing product "
            "identity marks, but add no subtitles, logos, watermarks, UI, or generated "
            "on-screen text."
        )

    def _existing(self, key: str) -> ExecutionJob | None:
        return self.session.scalar(
            select(ExecutionJob).where(ExecutionJob.idempotency_key == key)
        )

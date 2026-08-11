from __future__ import annotations

import hashlib
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.execution.handlers.youtube_publish import (
    YOUTUBE_PUBLISH_REFRESH_V1,
    YOUTUBE_PUBLISH_SUBMIT_V1,
    YouTubePublishRefreshV1Input,
    YouTubePublishSubmitV1Input,
    youtube_publish_task_digest,
)
from app.models import ExecutionJob, PublishTask
from app.schemas.execution import ExecutionJobCreate, ExecutionJobCreateRead
from app.schemas.social import PublishTaskIdentityRequest, YouTubePublishRequest
from app.services.execution_queue_service import ExecutionQueueService
from app.services.social_service import YouTubePublishingService
from app.services.video_artifact_storage import VideoArtifactStorage


class YouTubePublishJobService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        artifact_storage: VideoArtifactStorage,
    ) -> None:
        self.session = session
        self.settings = settings
        self.artifact_storage = artifact_storage

    def enqueue_submit(
        self, product_id: int, data: YouTubePublishRequest
    ) -> ExecutionJobCreateRead:
        idempotency_key = _job_key(YOUTUBE_PUBLISH_SUBMIT_V1, data.input_digest)
        existing = self._existing_job(idempotency_key)
        if existing is not None:
            self._validate_submit_reuse(existing, product_id, data)
            return ExecutionJobCreateRead(
                job=ExecutionQueueService(self.session).get(existing.id),
                reused=True,
            )

        service = YouTubePublishingService(
            self.session, self.settings, None, self.artifact_storage
        )
        checked = service.preflight(
            product_id, data, expires_at=data.preflight_expires_at
        )
        if not checked.ready:
            raise AppError("YouTube publishing Preflight is blocked", 409)
        if checked.input_digest != data.input_digest:
            raise AppError("YouTube publishing frozen input has changed", 409)
        if checked.preflight_digest != data.preflight_digest:
            raise AppError("YouTube publishing Preflight digest mismatch", 409)

        task = self._prepare_publish_task(product_id, data)
        payload = YouTubePublishSubmitV1Input(
            product_id=product_id,
            social_account_id=checked.social_account_id,
            channel_id=checked.channel_id,
            artifact_id=checked.artifact_id,
            render_task_id=checked.render_task_id,
            video_project_id=checked.video_project_id,
            copy_matrix_id=checked.copy_matrix_id,
            publish_task_id=task.id,
            frozen_input_digest=checked.input_digest,
            preflight_digest=checked.preflight_digest,
            preflight_expires_at=checked.expires_at,
        )
        return ExecutionQueueService(self.session).create(
            ExecutionJobCreate(
                job_type=YOUTUBE_PUBLISH_SUBMIT_V1,
                source_type="product",
                source_id=product_id,
                input_digest=checked.input_digest,
                idempotency_key=idempotency_key,
                input_payload=payload.model_dump(mode="json"),
                concurrency_key=f"youtube-publish-task-{task.id}",
                estimated_cost=Decimal("0"),
                currency="USD",
                cost_confirmed=True,
                max_attempts=1,
            )
        )

    def enqueue_refresh(
        self, task_id: int, data: PublishTaskIdentityRequest
    ) -> ExecutionJobCreateRead:
        task = self.session.get(PublishTask, task_id)
        if task is None or task.product_id != data.product_id:
            raise AppError("Publish task not found for Product", 404)
        idempotency_key = _job_key(
            YOUTUBE_PUBLISH_REFRESH_V1,
            f"{task.id}:{data.refresh_request_id}",
        )
        existing = self._existing_job(idempotency_key)
        if existing is not None:
            self._validate_refresh_reuse(existing, task, data)
            return ExecutionJobCreateRead(
                job=ExecutionQueueService(self.session).get(existing.id),
                reused=True,
            )
        if task.status not in {"SUBMITTED", "PROCESSING"}:
            raise AppError("Publish task cannot be refreshed", 409)
        if not task.provider_video_id:
            raise AppError("Provider video identity is unavailable", 409)
        digest = youtube_publish_task_digest(task)
        payload = YouTubePublishRefreshV1Input(
            product_id=task.product_id,
            social_account_id=task.social_account_id,
            publish_task_id=task.id,
            frozen_task_digest=digest,
            refresh_request_id=data.refresh_request_id,
        )
        return ExecutionQueueService(self.session).create(
            ExecutionJobCreate(
                job_type=YOUTUBE_PUBLISH_REFRESH_V1,
                source_type="publish_task",
                source_id=task.id,
                input_digest=digest,
                idempotency_key=idempotency_key,
                input_payload=payload.model_dump(mode="json"),
                concurrency_key=f"youtube-publish-task-{task.id}",
                estimated_cost=Decimal("0"),
                currency="USD",
                cost_confirmed=True,
                max_attempts=1,
            )
        )

    def _prepare_publish_task(
        self, product_id: int, data: YouTubePublishRequest
    ) -> PublishTask:
        key = _task_key(data.input_digest)
        existing = self.session.scalar(
            select(PublishTask).where(PublishTask.idempotency_key == key)
        )
        if existing is not None:
            if not _publish_task_matches(existing, product_id, data):
                raise AppError("Publish task identity mismatch", 409)
            return existing
        task = PublishTask(
            product_id=product_id,
            social_account_id=data.social_account_id,
            artifact_id=data.artifact_id,
            platform="youtube",
            idempotency_key=key,
            request_digest=data.input_digest,
            preflight_digest=data.preflight_digest,
            title=data.title,
            description=data.description,
            tags=data.tags,
            privacy_status="private",
            made_for_kids=bool(data.made_for_kids),
            synthetic_media=True,
            notify_subscribers=False,
            status="CREATED",
        )
        self.session.add(task)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            concurrent = self.session.scalar(
                select(PublishTask).where(PublishTask.idempotency_key == key)
            )
            if concurrent is None or not _publish_task_matches(
                concurrent, product_id, data
            ):
                raise AppError(
                    "Publish task conflicts with existing input", 409
                ) from None
            return concurrent
        self.session.refresh(task)
        return task

    def _existing_job(self, key: str) -> ExecutionJob | None:
        return self.session.scalar(
            select(ExecutionJob).where(ExecutionJob.idempotency_key == key)
        )

    def _validate_submit_reuse(
        self,
        job: ExecutionJob,
        product_id: int,
        data: YouTubePublishRequest,
    ) -> None:
        try:
            payload = YouTubePublishSubmitV1Input.model_validate(job.input_payload)
        except ValidationError:
            raise AppError("YouTube publish Job identity mismatch", 409) from None
        task = self.session.get(PublishTask, payload.publish_task_id)
        if (
            job.job_type != YOUTUBE_PUBLISH_SUBMIT_V1
            or job.source_type != "product"
            or job.source_id != product_id
            or job.input_digest != data.input_digest
            or job.input_digest != payload.frozen_input_digest
            or payload.product_id != product_id
            or payload.social_account_id != data.social_account_id
            or payload.artifact_id != data.artifact_id
            or task is None
            or not _publish_task_matches(task, product_id, data)
        ):
            raise AppError("YouTube publish Job identity mismatch", 409)

    def _validate_refresh_reuse(
        self,
        job: ExecutionJob,
        task: PublishTask,
        data: PublishTaskIdentityRequest,
    ) -> None:
        try:
            payload = YouTubePublishRefreshV1Input.model_validate(job.input_payload)
        except ValidationError:
            raise AppError("YouTube refresh Job identity mismatch", 409) from None
        if (
            job.job_type != YOUTUBE_PUBLISH_REFRESH_V1
            or job.source_type != "publish_task"
            or job.source_id != task.id
            or job.input_digest != payload.frozen_task_digest
            or payload.product_id != data.product_id
            or payload.product_id != task.product_id
            or payload.social_account_id != task.social_account_id
            or payload.publish_task_id != task.id
            or payload.refresh_request_id != data.refresh_request_id
        ):
            raise AppError("YouTube refresh Job identity mismatch", 409)


def _job_key(job_type: str, material: str) -> str:
    digest = hashlib.sha256(f"{job_type}:{material}".encode()).hexdigest()
    return f"{job_type}:{digest}"


def _task_key(input_digest: str) -> str:
    return f"youtube-publish:{input_digest}"


def _publish_task_matches(
    task: PublishTask,
    product_id: int,
    data: YouTubePublishRequest,
) -> bool:
    return (
        task.product_id == product_id
        and task.social_account_id == data.social_account_id
        and task.artifact_id == data.artifact_id
        and task.request_digest == data.input_digest
        and task.title == data.title
        and task.description == data.description
        and task.tags == data.tags
        and task.privacy_status == "private"
        and task.made_for_kids is bool(data.made_for_kids)
        and task.synthetic_media is True
        and task.notify_subscribers is False
        and task.platform == "youtube"
    )

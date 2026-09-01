from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.execution.handlers.instagram_publish import (
    INSTAGRAM_PUBLISH_FINALIZE_V1,
    INSTAGRAM_PUBLISH_REFRESH_V1,
    INSTAGRAM_PUBLISH_SUBMIT_V1,
    InstagramPublishFinalizeV1Input,
    InstagramPublishRefreshV1Input,
    InstagramPublishSubmitV1Input,
)
from app.models import ExecutionJob, PublishTask
from app.repositories.social import SocialRepository
from app.schemas.execution import ExecutionJobCreate, ExecutionJobCreateRead
from app.schemas.social import (
    InstagramFinalizeRequest,
    InstagramPublishRequest,
    PublishTaskIdentityRequest,
)
from app.services.execution_queue_service import ExecutionQueueService
from app.services.instagram_media_probe import InstagramMediaProbe
from app.services.instagram_publish_preflight import InstagramPublishPreflightService
from app.services.instagram_publish_service import (
    InstagramPublishService,
    instagram_finalize_input_digest,
    instagram_finalize_preflight_digest,
    instagram_job_input_digest,
    instagram_refresh_task_digest,
)
from app.services.video_artifact_storage import VideoArtifactStorage


class InstagramPublishJobService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        storage: VideoArtifactStorage,
        media_probe: InstagramMediaProbe,
    ) -> None:
        self.session = session
        self.settings = settings
        self.storage = storage
        self.media_probe = media_probe
        self.social = SocialRepository(session)

    def enqueue_submit(
        self, product_id: int, data: InstagramPublishRequest
    ) -> ExecutionJobCreateRead:
        key = _key(INSTAGRAM_PUBLISH_SUBMIT_V1, data.input_digest)
        existing = self._existing(key)
        if existing is not None:
            self._validate_submit_reuse(existing, product_id, data)
            return self._reused(existing)
        checked = InstagramPublishPreflightService(
            self.session, self.settings, self.storage, self.media_probe
        ).run(product_id, data, expires_at=data.preflight_expires_at)
        if (
            not checked.ready
            or checked.input_digest != data.input_digest
            or checked.preflight_digest != data.preflight_digest
        ):
            raise AppError("Instagram publishing Preflight identity mismatch", 409)
        task = self._prepare_task(product_id, data)
        digest = instagram_job_input_digest(checked.input_digest, task.id)
        payload = InstagramPublishSubmitV1Input(
            product_id=product_id,
            social_account_id=checked.social_account_id,
            professional_account_id=checked.professional_account_id,
            artifact_id=checked.artifact_id,
            render_task_id=checked.render_task_id,
            video_project_id=checked.video_project_id,
            copy_matrix_id=checked.copy_matrix_id,
            marketing_strategy_id=checked.marketing_strategy_id,
            publish_task_id=task.id,
            preflight_input_digest=checked.input_digest,
            frozen_input_digest=digest,
            preflight_digest=checked.preflight_digest,
            preflight_expires_at=checked.expires_at,
            content_type=checked.content_type,
            size_bytes=checked.size_bytes,
            sha256=checked.sha256,
            safe_path_digest=checked.safe_path_digest,
            media=checked.media,
        )
        return self._create(
            INSTAGRAM_PUBLISH_SUBMIT_V1,
            "product",
            product_id,
            digest,
            key,
            payload.model_dump(mode="json"),
            task.id,
        )

    def enqueue_refresh(
        self, task_id: int, data: PublishTaskIdentityRequest
    ) -> ExecutionJobCreateRead:
        task = self._task(task_id, data.product_id)
        key = _key(INSTAGRAM_PUBLISH_REFRESH_V1, f"{task.id}:{data.refresh_request_id}")
        existing = self._existing(key)
        if existing is not None:
            self._validate_refresh_reuse(existing, task, data)
            return self._reused(existing)
        if task.status != "PROCESSING" or not task.provider_container_id:
            raise AppError("Instagram PublishTask cannot be refreshed", 409)
        digest = instagram_refresh_task_digest(task)
        payload = InstagramPublishRefreshV1Input(
            product_id=task.product_id,
            social_account_id=task.social_account_id,
            publish_task_id=task.id,
            frozen_task_digest=digest,
            refresh_request_id=data.refresh_request_id,
        )
        return self._create(
            INSTAGRAM_PUBLISH_REFRESH_V1,
            "publish_task",
            task.id,
            digest,
            key,
            payload.model_dump(mode="json"),
            task.id,
        )

    def enqueue_finalize(
        self, task_id: int, data: InstagramFinalizeRequest
    ) -> ExecutionJobCreateRead:
        task = self._task(task_id, data.product_id)
        key = _key(
            INSTAGRAM_PUBLISH_FINALIZE_V1, f"{task.id}:{data.finalize_request_id}"
        )
        existing = self._existing(key)
        if existing is not None:
            self._validate_finalize_reuse(existing, task, data)
            return self._reused(existing)
        if task.status != "READY_TO_PUBLISH" or not task.provider_container_id:
            raise AppError("Instagram PublishTask is not ready for public publish", 409)
        service = InstagramPublishService(
            self.session, self.settings, self.storage, self.media_probe
        )
        account = service.account(task)
        digest = instagram_finalize_input_digest(task, account)
        expires = _utc(data.preflight_expires_at)
        if (
            expires <= datetime.now(UTC)
            or digest != data.input_digest
            or instagram_finalize_preflight_digest(digest, expires)
            != data.preflight_digest
        ):
            raise AppError("Instagram finalize Preflight identity mismatch", 409)
        payload = InstagramPublishFinalizeV1Input(
            product_id=task.product_id,
            social_account_id=task.social_account_id,
            publish_task_id=task.id,
            frozen_task_digest=digest,
            preflight_digest=data.preflight_digest,
            preflight_expires_at=expires,
            finalize_request_id=data.finalize_request_id,
        )
        return self._create(
            INSTAGRAM_PUBLISH_FINALIZE_V1,
            "publish_task",
            task.id,
            digest,
            key,
            payload.model_dump(mode="json"),
            task.id,
        )

    def _prepare_task(
        self, product_id: int, data: InstagramPublishRequest
    ) -> PublishTask:
        key = self.social.scoped_idempotency_key(
            f"instagram-publish:{data.input_digest}"
        )
        task = self.social.get_publish_task_by_key(key)
        if task is not None:
            if not _task_matches(task, product_id, data):
                raise AppError("Instagram PublishTask identity mismatch", 409)
            return task
        task = PublishTask(
            workspace_id=self.social.workspace_id,
            product_id=product_id,
            social_account_id=data.social_account_id,
            artifact_id=data.artifact_id,
            platform="instagram",
            idempotency_key=key,
            request_digest=data.input_digest,
            preflight_digest=data.preflight_digest,
            title=data.title,
            description=data.description,
            tags=data.tags,
            privacy_status="public",
            made_for_kids=False,
            synthetic_media=True,
            notify_subscribers=False,
            share_to_feed=data.share_to_feed,
            status="CREATED",
        )
        self.session.add(task)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            task = self.social.get_publish_task_by_key(key)
            if task is None or not _task_matches(task, product_id, data):
                raise AppError(
                    "Instagram PublishTask conflicts with existing input", 409
                ) from None
        self.session.refresh(task)
        return task

    def _validate_submit_reuse(
        self, job: ExecutionJob, product_id: int, data: InstagramPublishRequest
    ) -> None:
        try:
            payload = InstagramPublishSubmitV1Input.model_validate(job.input_payload)
        except ValidationError:
            raise AppError("Instagram publish Job identity mismatch", 409) from None
        task = self.social.get_publish_task(payload.publish_task_id)
        expected = instagram_job_input_digest(
            data.input_digest, payload.publish_task_id
        )
        try:
            frozen = (
                InstagramPublishService(
                    self.session, self.settings, self.storage, self.media_probe
                ).freeze_task(task)
                if task is not None
                else None
            )
        except AppError:
            frozen = None
        if (
            job.job_type != INSTAGRAM_PUBLISH_SUBMIT_V1
            or job.source_type != "product"
            or job.source_id != product_id
            or job.input_digest != expected
            or payload.frozen_input_digest != expected
            or payload.preflight_input_digest != data.input_digest
            or payload.product_id != product_id
            or payload.social_account_id != data.social_account_id
            or payload.artifact_id != data.artifact_id
            or task is None
            or not _task_matches(task, product_id, data)
            or frozen is None
            or frozen.input_digest != data.input_digest
            or payload.professional_account_id != frozen.professional_account_id
            or payload.render_task_id != frozen.render_task_id
            or payload.video_project_id != frozen.video_project_id
            or payload.copy_matrix_id != frozen.copy_matrix_id
            or payload.marketing_strategy_id != frozen.marketing_strategy_id
            or payload.content_type != frozen.content_type
            or payload.size_bytes != frozen.size_bytes
            or payload.sha256 != frozen.sha256
            or payload.safe_path_digest != frozen.safe_path_digest
            or payload.media.model_dump() != frozen.media.stable_payload()
        ):
            raise AppError("Instagram publish Job identity mismatch", 409)

    def _validate_refresh_reuse(
        self, job: ExecutionJob, task: PublishTask, data: PublishTaskIdentityRequest
    ) -> None:
        try:
            payload = InstagramPublishRefreshV1Input.model_validate(job.input_payload)
        except ValidationError:
            raise AppError("Instagram refresh Job identity mismatch", 409) from None
        if (
            job.job_type != INSTAGRAM_PUBLISH_REFRESH_V1
            or job.source_type != "publish_task"
            or job.source_id != task.id
            or job.input_digest != payload.frozen_task_digest
            or payload.product_id != task.product_id
            or payload.social_account_id != task.social_account_id
            or payload.publish_task_id != task.id
            or payload.refresh_request_id != data.refresh_request_id
        ):
            raise AppError("Instagram refresh Job identity mismatch", 409)

    def _validate_finalize_reuse(
        self, job: ExecutionJob, task: PublishTask, data: InstagramFinalizeRequest
    ) -> None:
        try:
            payload = InstagramPublishFinalizeV1Input.model_validate(job.input_payload)
        except ValidationError:
            raise AppError("Instagram finalize Job identity mismatch", 409) from None
        if (
            job.job_type != INSTAGRAM_PUBLISH_FINALIZE_V1
            or job.source_type != "publish_task"
            or job.source_id != task.id
            or data.input_digest != payload.frozen_task_digest
            or job.input_digest != data.input_digest
            or job.input_digest != payload.frozen_task_digest
            or data.preflight_digest != payload.preflight_digest
            or _utc(data.preflight_expires_at) != _utc(payload.preflight_expires_at)
            or payload.preflight_digest
            != instagram_finalize_preflight_digest(
                payload.frozen_task_digest, payload.preflight_expires_at
            )
            or payload.product_id != task.product_id
            or payload.social_account_id != task.social_account_id
            or payload.publish_task_id != task.id
            or payload.finalize_request_id != data.finalize_request_id
        ):
            raise AppError("Instagram finalize Job identity mismatch", 409)

    def _task(self, task_id: int, product_id: int) -> PublishTask:
        return InstagramPublishService(
            self.session, self.settings, self.storage, self.media_probe
        ).get_task(task_id, product_id)

    def _existing(self, key: str) -> ExecutionJob | None:
        statement = select(ExecutionJob).where(ExecutionJob.idempotency_key == key)
        workspace_id = self.social.workspace_id
        if workspace_id is not None:
            statement = statement.where(ExecutionJob.workspace_id == workspace_id)
        return self.session.scalar(statement)

    def _reused(self, job: ExecutionJob) -> ExecutionJobCreateRead:
        return ExecutionJobCreateRead(
            job=ExecutionQueueService(self.session).get(job.id), reused=True
        )

    def _create(
        self,
        job_type: str,
        source_type: str,
        source_id: int,
        digest: str,
        key: str,
        payload: dict[str, object],
        task_id: int,
    ) -> ExecutionJobCreateRead:
        return ExecutionQueueService(self.session).create(
            ExecutionJobCreate(
                job_type=job_type,
                source_type=source_type,
                source_id=source_id,
                input_digest=digest,
                idempotency_key=key,
                input_payload=payload,
                concurrency_key=f"instagram-publish-task-{task_id}",
                estimated_cost=Decimal("0"),
                currency="USD",
                cost_confirmed=True,
                max_attempts=1,
            )
        )


def _task_matches(
    task: PublishTask, product_id: int, data: InstagramPublishRequest
) -> bool:
    return (
        task.product_id == product_id
        and task.social_account_id == data.social_account_id
        and task.artifact_id == data.artifact_id
        and task.request_digest == data.input_digest
        and task.title == data.title
        and task.description == data.description
        and task.tags == data.tags
        and task.platform == "instagram"
        and task.privacy_status == "public"
        and task.made_for_kids is False
        and task.synthetic_media is True
        and task.notify_subscribers is False
        and task.share_to_feed is data.share_to_feed
    )


def _key(job_type: str, material: str) -> str:
    return f"{job_type}:{hashlib.sha256(f'{job_type}:{material}'.encode()).hexdigest()}"


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)

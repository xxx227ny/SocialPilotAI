from __future__ import annotations

import hashlib
import time
from copy import copy
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.execution.handlers.tiktok_publish import (
    TIKTOK_PUBLISH_CREATOR_INFO_V1,
    TIKTOK_PUBLISH_REFRESH_V1,
    TIKTOK_PUBLISH_SUBMIT_V1,
    TikTokCreatorInfoV1Input,
    TikTokRefreshV1Input,
    TikTokSubmitV1Input,
)
from app.models.execution import ExecutionJob
from app.models.social import PublishTask, SocialAccount, TikTokCreatorInfoSnapshot
from app.schemas.execution import ExecutionJobCreate, ExecutionJobCreateRead
from app.schemas.social import (
    TikTokCreatorInfoRequest,
    TikTokPublishingMetadata,
    TikTokPublishRequest,
    TikTokRefreshRequest,
)
from app.services.execution_queue_service import ExecutionQueueService
from app.services.tiktok_media_probe import TikTokMediaProbe
from app.services.tiktok_publish_preflight import (
    TikTokPublishPreflightService,
    preflight_digest,
)
from app.services.tiktok_publish_service import tiktok_refresh_task_digest
from app.services.video_artifact_storage import VideoArtifactStorage


class TikTokPublishJobService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        storage: VideoArtifactStorage,
        probe: TikTokMediaProbe,
    ) -> None:
        self.session, self.settings, self.storage, self.probe = (
            session,
            settings,
            storage,
            probe,
        )

    def enqueue_creator_info(
        self, product_id: int, data: TikTokCreatorInfoRequest
    ) -> ExecutionJobCreateRead:
        self._enabled()
        account = self.session.get(SocialAccount, data.social_account_id)
        if (
            account is None
            or account.product_id != product_id
            or account.platform != "tiktok"
            or account.connection_status != "CONNECTED"
        ):
            raise AppError("TikTok account not connected for Product", 409)
        digest = _digest(
            f"creator:{product_id}:{account.id}:{account.provider_account_id}:"
            f"{account.updated_at.isoformat()}:{data.request_id}"
        )
        payload = TikTokCreatorInfoV1Input(
            product_id=product_id,
            social_account_id=account.id,
            request_digest=digest,
            request_id=data.request_id,
            provider_account_id=account.provider_account_id,
        )
        existing = self._existing(_key(TIKTOK_PUBLISH_CREATOR_INFO_V1, digest))
        if existing is not None:
            self._validate_creator_reuse(existing, product_id, data, account, digest)
            return self._reused(existing)
        return self._create(
            TIKTOK_PUBLISH_CREATOR_INFO_V1,
            "social_account",
            account.id,
            digest,
            _key(TIKTOK_PUBLISH_CREATOR_INFO_V1, digest),
            payload.model_dump(mode="json"),
            f"tiktok-account-{account.id}",
        )

    def enqueue_submit(
        self, product_id: int, data: TikTokPublishRequest
    ) -> ExecutionJobCreateRead:
        self._enabled()
        key = _key(TIKTOK_PUBLISH_SUBMIT_V1, data.input_digest)
        existing = self._existing(key)
        if existing:
            self._validate_submit_reuse(existing, product_id, data)
            return self._reused(existing)
        checked = TikTokPublishPreflightService(
            self.session, self.settings, self.storage, self.probe
        ).run(product_id, data, expires_at=data.preflight_expires_at)
        if (
            not checked.ready
            or checked.input_digest != data.input_digest
            or checked.preflight_digest != data.preflight_digest
        ):
            raise AppError("TikTok publishing Preflight identity mismatch", 409)
        task = PublishTask(
            product_id=product_id,
            social_account_id=data.social_account_id,
            artifact_id=data.artifact_id,
            platform="tiktok",
            idempotency_key=key,
            request_digest=data.input_digest,
            preflight_digest=data.preflight_digest,
            title=data.title,
            description=data.description,
            tags=data.tags,
            privacy_status=data.privacy_status,
            made_for_kids=False,
            synthetic_media=True,
            notify_subscribers=False,
            status="CREATED",
            disable_comment=data.disable_comment,
            disable_duet=data.disable_duet,
            disable_stitch=data.disable_stitch,
            brand_content_toggle=data.brand_content_toggle,
            brand_organic_toggle=data.brand_organic_toggle,
        )
        try:
            self.session.add(task)
            self.session.flush()
            payload = TikTokSubmitV1Input(
                product_id=product_id,
                publish_task_id=task.id,
                creator_info_snapshot_id=data.creator_info_snapshot_id,
                frozen_input_digest=data.input_digest,
                preflight_digest=data.preflight_digest,
                preflight_expires_at=data.preflight_expires_at,
                metadata=data,
            )
            job = ExecutionJob(
                job_type=TIKTOK_PUBLISH_SUBMIT_V1,
                source_type="product",
                source_id=product_id,
                input_digest=data.input_digest,
                idempotency_key=key,
                input_payload=payload.model_dump(mode="json"),
                priority=0,
                concurrency_key=f"tiktok-publish-task-{task.id}",
                estimated_cost=Decimal("0"),
                currency="USD",
                cost_confirmed=True,
                status="QUEUED",
                attempt_count=0,
                max_attempts=1,
                uncertain=False,
            )
            self.session.add(job)
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            last_mismatch: AppError | None = None
            for attempt in range(3):
                with Session(
                    bind=self.session.get_bind(), expire_on_commit=False
                ) as recovery:
                    recovery_service = TikTokPublishJobService(
                        recovery, self.settings, self.storage, self.probe
                    )
                    concurrent = recovery_service._existing(key)
                    if concurrent is not None:
                        try:
                            recovery_service._validate_submit_reuse(
                                concurrent, product_id, data
                            )
                        except AppError as exc:
                            last_mismatch = exc
                        else:
                            return recovery_service._reused(concurrent)
                if attempt < 2:
                    time.sleep(0.01)
            if last_mismatch is not None:
                raise last_mismatch from None
            raise
        except Exception:
            self.session.rollback()
            raise
        return ExecutionJobCreateRead(
            job=ExecutionQueueService(self.session).get(job.id), reused=False
        )

    def enqueue_refresh(
        self, task_id: int, data: TikTokRefreshRequest
    ) -> ExecutionJobCreateRead:
        self._enabled()
        task = self.session.get(PublishTask, task_id)
        if (
            task is None
            or task.product_id != data.product_id
            or task.platform != "tiktok"
        ):
            raise AppError("TikTok PublishTask not found", 404)
        key = _key(TIKTOK_PUBLISH_REFRESH_V1, f"{task.id}:{data.refresh_request_id}")
        existing = self._existing(key)
        if existing is not None:
            self._validate_refresh_reuse(existing, task, data)
            return self._reused(existing)
        if task.status != "PROCESSING" or not task.provider_publish_id:
            raise AppError("TikTok PublishTask cannot be refreshed", 409)
        digest = tiktok_refresh_task_digest(task)
        payload = TikTokRefreshV1Input(
            product_id=task.product_id,
            publish_task_id=task.id,
            social_account_id=task.social_account_id,
            artifact_id=task.artifact_id,
            provider_publish_id=task.provider_publish_id,
            frozen_task_digest=digest,
            refresh_request_id=data.refresh_request_id,
        )
        return self._create(
            TIKTOK_PUBLISH_REFRESH_V1,
            "publish_task",
            task.id,
            digest,
            key,
            payload.model_dump(mode="json"),
            f"tiktok-publish-task-{task.id}",
        )

    def _create(
        self,
        job_type: str,
        source_type: str,
        source_id: int,
        digest: str,
        key: str,
        payload: dict[str, object],
        concurrency: str,
    ) -> ExecutionJobCreateRead:
        return ExecutionQueueService(self.session).create(
            ExecutionJobCreate(
                job_type=job_type,
                source_type=source_type,
                source_id=source_id,
                input_digest=digest,
                idempotency_key=key,
                input_payload=payload,
                concurrency_key=concurrency,
                estimated_cost=Decimal("0"),
                currency="USD",
                cost_confirmed=True,
                max_attempts=1,
            )
        )

    def _reused(self, job: ExecutionJob) -> ExecutionJobCreateRead:
        return ExecutionJobCreateRead(
            job=ExecutionQueueService(self.session).get(job.id), reused=True
        )

    def _validate_creator_reuse(
        self,
        job: ExecutionJob,
        product_id: int,
        data: TikTokCreatorInfoRequest,
        account: SocialAccount,
        digest: str,
    ) -> None:
        try:
            payload = TikTokCreatorInfoV1Input.model_validate(job.input_payload)
        except Exception:
            raise AppError("TikTok Creator Job identity mismatch", 409) from None
        if (
            job.job_type != TIKTOK_PUBLISH_CREATOR_INFO_V1
            or job.source_type != "social_account"
            or job.source_id != account.id
            or job.input_digest != digest
            or payload.product_id != product_id
            or payload.social_account_id != account.id
            or payload.request_digest != digest
            or payload.request_id != data.request_id
            or payload.provider_account_id != account.provider_account_id
            or account.product_id != product_id
            or account.platform != "tiktok"
            or account.connection_status != "CONNECTED"
        ):
            raise AppError("TikTok Creator Job identity mismatch", 409)

    def _validate_submit_reuse(
        self, job: ExecutionJob, product_id: int, data: TikTokPublishRequest
    ) -> None:
        try:
            payload = TikTokSubmitV1Input.model_validate(job.input_payload)
        except Exception:
            raise AppError("TikTok Submit Job identity mismatch", 409) from None
        task = self.session.get(PublishTask, payload.publish_task_id)
        snapshot = self.session.get(
            TikTokCreatorInfoSnapshot, data.creator_info_snapshot_id
        )
        try:
            frozen = TikTokPublishPreflightService(
                self.session, self.settings, self.storage, self.probe
            ).freeze(product_id, data)
        except AppError:
            frozen = None
        if (
            job.job_type != TIKTOK_PUBLISH_SUBMIT_V1
            or job.source_type != "product"
            or job.source_id != product_id
            or job.input_digest != data.input_digest
            or payload.frozen_input_digest != data.input_digest
            or payload.product_id != product_id
            or payload.preflight_digest != data.preflight_digest
            or _utc(payload.preflight_expires_at) != _utc(data.preflight_expires_at)
            or preflight_digest(
                payload.frozen_input_digest, payload.preflight_expires_at
            )
            != payload.preflight_digest
            or payload.creator_info_snapshot_id != data.creator_info_snapshot_id
            or payload.metadata
            != TikTokPublishingMetadata.model_validate(data.model_dump())
            or task is None
            or task.product_id != product_id
            or task.social_account_id != data.social_account_id
            or task.artifact_id != data.artifact_id
            or task.platform != "tiktok"
            or task.request_digest != data.input_digest
            or task.title != data.title
            or task.description != data.description
            or task.tags != data.tags
            or task.privacy_status != data.privacy_status
            or task.disable_comment != data.disable_comment
            or task.disable_duet != data.disable_duet
            or task.disable_stitch != data.disable_stitch
            or task.brand_content_toggle != data.brand_content_toggle
            or task.brand_organic_toggle != data.brand_organic_toggle
            or snapshot is None
            or snapshot.product_id != product_id
            or snapshot.social_account_id != data.social_account_id
            or frozen is None
            or frozen.input_digest != data.input_digest
        ):
            raise AppError("TikTok Submit Job identity mismatch", 409)

    def _validate_refresh_reuse(
        self, job: ExecutionJob, task: PublishTask, data: TikTokRefreshRequest
    ) -> None:
        try:
            payload = TikTokRefreshV1Input.model_validate(job.input_payload)
        except Exception:
            raise AppError("TikTok Refresh Job identity mismatch", 409) from None
        account = self.session.get(SocialAccount, task.social_account_id)
        frozen_task = copy(task)
        frozen_task.status = "PROCESSING"
        expected_frozen_digest = tiktok_refresh_task_digest(frozen_task)
        if (
            job.job_type != TIKTOK_PUBLISH_REFRESH_V1
            or job.source_type != "publish_task"
            or job.source_id != task.id
            or job.input_digest != payload.frozen_task_digest
            or payload.frozen_task_digest != expected_frozen_digest
            or payload.product_id != task.product_id
            or payload.publish_task_id != task.id
            or payload.social_account_id != task.social_account_id
            or payload.artifact_id != task.artifact_id
            or payload.provider_publish_id != task.provider_publish_id
            or payload.refresh_request_id != data.refresh_request_id
            or task.product_id != data.product_id
            or task.platform != "tiktok"
            or not task.provider_publish_id
            or account is None
            or account.product_id != task.product_id
            or account.platform != "tiktok"
        ):
            raise AppError("TikTok Refresh Job identity mismatch", 409)

    def _existing(self, key: str) -> ExecutionJob | None:
        return self.session.scalar(
            select(ExecutionJob).where(ExecutionJob.idempotency_key == key)
        )

    def _enabled(self) -> None:
        if not self.settings.enable_tiktok_publishing:
            raise AppError("TikTok publishing is disabled by the server", 503)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _key(job_type: str, material: str) -> str:
    return f"{job_type}:{_digest(f'{job_type}:{material}')}"


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

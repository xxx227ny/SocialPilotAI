from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.execution.contracts import (
    ExecutionContext,
    HandlerResult,
    LeaseLostError,
    WorkerStopRequested,
)
from app.models import PublishTask
from app.providers.instagram_provider import InstagramProvider
from app.repositories.social import SocialRepository
from app.schemas.social import InstagramMediaSpecificationRead
from app.services.instagram_media_probe import InstagramMediaProbe
from app.services.instagram_publish_service import (
    InstagramPublishService,
    instagram_finalize_input_digest,
    instagram_finalize_preflight_digest,
    instagram_job_input_digest,
    instagram_refresh_task_digest,
)
from app.services.social_security import TokenCipher
from app.services.video_artifact_storage import VideoArtifactStorage

INSTAGRAM_PUBLISH_SUBMIT_V1 = "instagram.publish.submit.v1"
INSTAGRAM_PUBLISH_REFRESH_V1 = "instagram.publish.refresh.v1"
INSTAGRAM_PUBLISH_FINALIZE_V1 = "instagram.publish.finalize.v1"


class _SessionFactory(Protocol):
    def __call__(self) -> Session: ...


class InstagramPublishSubmitV1Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: int = Field(gt=0)
    social_account_id: int = Field(gt=0)
    professional_account_id: str = Field(min_length=1, max_length=255)
    artifact_id: int = Field(gt=0)
    render_task_id: int = Field(gt=0)
    video_project_id: int = Field(gt=0)
    copy_matrix_id: int = Field(gt=0)
    marketing_strategy_id: int = Field(gt=0)
    publish_task_id: int = Field(gt=0)
    preflight_input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    frozen_input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_expires_at: datetime
    content_type: str
    size_bytes: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    safe_path_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    media: InstagramMediaSpecificationRead


class InstagramPublishRefreshV1Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: int = Field(gt=0)
    social_account_id: int = Field(gt=0)
    publish_task_id: int = Field(gt=0)
    frozen_task_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    refresh_request_id: str = Field(min_length=16, max_length=128)


class InstagramPublishFinalizeV1Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: int = Field(gt=0)
    social_account_id: int = Field(gt=0)
    publish_task_id: int = Field(gt=0)
    frozen_task_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_expires_at: datetime
    finalize_request_id: str = Field(min_length=16, max_length=128)


class InstagramPublishSubmitV1Handler:
    job_type = INSTAGRAM_PUBLISH_SUBMIT_V1
    input_schema = InstagramPublishSubmitV1Input

    def __init__(
        self,
        *,
        session_factory: _SessionFactory,
        provider: InstagramProvider,
        settings: Settings,
        artifact_storage: VideoArtifactStorage,
        media_probe: InstagramMediaProbe,
    ) -> None:
        self.session_factory = session_factory
        self.provider = provider
        self.settings = settings
        self.artifact_storage = artifact_storage
        self.media_probe = media_probe

    def execute(self, context: ExecutionContext, payload: BaseModel) -> HandlerResult:
        data = InstagramPublishSubmitV1Input.model_validate(payload)
        with self.session_factory() as session:
            task = SocialRepository(session).get_publish_task(data.publish_task_id)
            service = InstagramPublishService(
                session,
                self.settings,
                self.artifact_storage,
                self.media_probe,
            )
            try:
                if task is None or not _submit_identity_matches(service, task, data):
                    if task is not None:
                        _mark_failed(session, task, "frozen_input_mismatch")
                    return HandlerResult.failed("INSTAGRAM_FROZEN_INPUT_MISMATCH")
                if (
                    task.status == "PROCESSING"
                    and task.provider_container_id
                    and task.resumable_session_ciphertext
                ):
                    return _success(task)
                if task.provider_container_id or task.resumable_session_ciphertext:
                    _mark_unknown(session, task, "instagram_submit_already_possible")
                    return HandlerResult.submit_unknown(
                        "INSTAGRAM_SUBMIT_ALREADY_POSSIBLE", provider_name="instagram"
                    )
                if task.status != "CREATED":
                    _mark_failed(session, task, "submit_state_invalid")
                    return HandlerResult.failed("INSTAGRAM_SUBMIT_STATE_INVALID")
                account = service.account(task)
                token = service.access_token(account)
                frozen = service.freeze_task(task)
            except AppError:
                if task is not None:
                    _mark_failed(session, task, "local_validation_failed")
                return HandlerResult.failed("INSTAGRAM_SUBMIT_VALIDATION_FAILED")

            try:
                context.before_provider_call(may_submit_external=True)
                container = asyncio.run(
                    self.provider.create_resumable_reel_container(
                        professional_account_id=account.provider_account_id,
                        access_token=token,
                        caption=frozen.caption,
                        share_to_feed=task.share_to_feed,
                    )
                )
                task.provider_container_id = container.container_id
                task.resumable_session_ciphertext = TokenCipher(self.settings).encrypt(
                    container.upload_uri
                )
                task.status = "UPLOADING"
                task.submitted_at = task.submitted_at or datetime.now(UTC)
                session.commit()
                context.before_provider_call(may_submit_external=True)
                asyncio.run(
                    self.provider.upload_reel_bytes(
                        upload_uri=container.upload_uri,
                        access_token=token,
                        path=frozen.verified.path,
                        size_bytes=frozen.size_bytes,
                    )
                )
                task.status = "PROCESSING"
                task.uncertain = False
                task.safe_error_code = None
                session.commit()
                return _success(task)
            except (LeaseLostError, WorkerStopRequested):
                raise
            except Exception:
                _mark_unknown(session, task, "instagram_submit_result_uncertain")
                return HandlerResult.submit_unknown(
                    "INSTAGRAM_SUBMIT_UNKNOWN", provider_name="instagram"
                )


class InstagramPublishRefreshV1Handler:
    job_type = INSTAGRAM_PUBLISH_REFRESH_V1
    input_schema = InstagramPublishRefreshV1Input

    def __init__(
        self,
        *,
        session_factory: _SessionFactory,
        provider: InstagramProvider,
        settings: Settings,
        artifact_storage: VideoArtifactStorage,
        media_probe: InstagramMediaProbe,
    ) -> None:
        self.session_factory = session_factory
        self.provider = provider
        self.settings = settings
        self.artifact_storage = artifact_storage
        self.media_probe = media_probe

    def execute(self, context: ExecutionContext, payload: BaseModel) -> HandlerResult:
        data = InstagramPublishRefreshV1Input.model_validate(payload)
        with self.session_factory() as session:
            task = SocialRepository(session).get_publish_task(data.publish_task_id)
            service = InstagramPublishService(
                session, self.settings, self.artifact_storage, self.media_probe
            )
            if (
                task is None
                or task.platform != "instagram"
                or task.product_id != data.product_id
                or task.social_account_id != data.social_account_id
                or instagram_refresh_task_digest(task) != data.frozen_task_digest
                or task.status != "PROCESSING"
                or not task.provider_container_id
            ):
                return HandlerResult.failed("INSTAGRAM_REFRESH_IDENTITY_MISMATCH")
            try:
                account = service.account(task)
                token = service.access_token(account)
            except AppError:
                return HandlerResult.failed("INSTAGRAM_REFRESH_VALIDATION_FAILED")
            try:
                context.before_provider_call(may_submit_external=False)
                result = asyncio.run(
                    self.provider.get_container_status(
                        container_id=task.provider_container_id,
                        access_token=token,
                    )
                )
            except (LeaseLostError, WorkerStopRequested):
                raise
            except Exception:
                return HandlerResult.failed("INSTAGRAM_STATUS_QUERY_FAILED")
            if result.status == "FINISHED":
                task.status = "READY_TO_PUBLISH"
                task.safe_error_code = None
            elif result.status in {"ERROR", "EXPIRED"}:
                task.status = "FAILED"
                task.safe_error_code = f"instagram_container_{result.status.casefold()}"
                task.completed_at = datetime.now(UTC)
            else:
                task.status = "PROCESSING"
            session.commit()
            return _success(task)


class InstagramPublishFinalizeV1Handler:
    job_type = INSTAGRAM_PUBLISH_FINALIZE_V1
    input_schema = InstagramPublishFinalizeV1Input

    def __init__(
        self,
        *,
        session_factory: _SessionFactory,
        provider: InstagramProvider,
        settings: Settings,
        artifact_storage: VideoArtifactStorage,
        media_probe: InstagramMediaProbe,
    ) -> None:
        self.session_factory = session_factory
        self.provider = provider
        self.settings = settings
        self.artifact_storage = artifact_storage
        self.media_probe = media_probe

    def execute(self, context: ExecutionContext, payload: BaseModel) -> HandlerResult:
        data = InstagramPublishFinalizeV1Input.model_validate(payload)
        with self.session_factory() as session:
            task = SocialRepository(session).get_publish_task(data.publish_task_id)
            service = InstagramPublishService(
                session, self.settings, self.artifact_storage, self.media_probe
            )
            try:
                if (
                    task is None
                    or task.platform != "instagram"
                    or task.product_id != data.product_id
                    or task.social_account_id != data.social_account_id
                    or task.status != "READY_TO_PUBLISH"
                    or not task.provider_container_id
                ):
                    return HandlerResult.failed("INSTAGRAM_FINALIZE_IDENTITY_MISMATCH")
                account = service.account(task)
                if (
                    instagram_finalize_input_digest(task, account)
                    != data.frozen_task_digest
                    or instagram_finalize_preflight_digest(
                        data.frozen_task_digest, data.preflight_expires_at
                    )
                    != data.preflight_digest
                ):
                    return HandlerResult.failed("INSTAGRAM_FINALIZE_DIGEST_MISMATCH")
                token = service.access_token(account)
            except AppError:
                return HandlerResult.failed("INSTAGRAM_FINALIZE_VALIDATION_FAILED")
            try:
                context.before_provider_call(may_submit_external=True)
                result = asyncio.run(
                    self.provider.publish_reel(
                        professional_account_id=account.provider_account_id,
                        container_id=task.provider_container_id,
                        access_token=token,
                    )
                )
                task.provider_video_id = result.media_id
                task.status = "SUCCEEDED"
                task.uncertain = False
                task.safe_error_code = None
                task.completed_at = datetime.now(UTC)
                session.commit()
                return _success(task)
            except (LeaseLostError, WorkerStopRequested):
                raise
            except Exception:
                _mark_unknown(session, task, "instagram_finalize_result_uncertain")
                return HandlerResult.submit_unknown(
                    "INSTAGRAM_FINALIZE_UNKNOWN", provider_name="instagram"
                )


def _submit_identity_matches(
    service: InstagramPublishService,
    task: PublishTask,
    data: InstagramPublishSubmitV1Input,
) -> bool:
    if (
        task.platform != "instagram"
        or task.product_id != data.product_id
        or task.social_account_id != data.social_account_id
        or task.artifact_id != data.artifact_id
        or task.request_digest != data.preflight_input_digest
        or data.frozen_input_digest
        != instagram_job_input_digest(data.preflight_input_digest, task.id)
    ):
        return False
    try:
        frozen = service.freeze_task(task)
    except AppError:
        return False
    return (
        frozen.input_digest == data.preflight_input_digest
        and frozen.professional_account_id == data.professional_account_id
        and frozen.render_task_id == data.render_task_id
        and frozen.video_project_id == data.video_project_id
        and frozen.copy_matrix_id == data.copy_matrix_id
        and frozen.marketing_strategy_id == data.marketing_strategy_id
        and frozen.content_type == data.content_type
        and frozen.size_bytes == data.size_bytes
        and frozen.sha256 == data.sha256
        and frozen.safe_path_digest == data.safe_path_digest
        and frozen.media.stable_payload() == data.media.model_dump()
    )


def _success(task: PublishTask) -> HandlerResult:
    return HandlerResult.succeeded(
        provider_name="instagram",
        result_entity_type="publish_task",
        result_entity_id=task.id,
    )


def _mark_failed(session: Session, task: PublishTask, code: str) -> None:
    try:
        task.status = "FAILED"
        task.safe_error_code = code
        task.uncertain = False
        task.completed_at = datetime.now(UTC)
        session.commit()
    except Exception:
        session.rollback()


def _mark_unknown(session: Session, task: PublishTask, code: str) -> None:
    task_id = task.id
    try:
        task.status = "SUBMIT_UNKNOWN"
        task.safe_error_code = code
        task.uncertain = True
        session.commit()
    except Exception:
        session.rollback()
        recovered = SocialRepository(session).get_publish_task(task_id)
        if recovered is not None:
            recovered.status = "SUBMIT_UNKNOWN"
            recovered.safe_error_code = code
            recovered.uncertain = True
            try:
                session.commit()
            except Exception:
                session.rollback()

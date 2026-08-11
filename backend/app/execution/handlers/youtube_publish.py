from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.execution.contracts import ExecutionContext, HandlerResult
from app.models import PublishTask
from app.providers.youtube_provider import (
    OAuthTokens,
    YouTubeProvider,
    YouTubeProviderError,
    YouTubeUploadResult,
    YouTubeVideoStatus,
)
from app.repositories.social import SocialRepository
from app.schemas.social import YouTubePublishingMetadata
from app.services.social_security import TokenCipher
from app.services.social_service import (
    SocialAuthorizationError,
    YouTubePublishingService,
)
from app.services.video_artifact_storage import VideoArtifactStorage

YOUTUBE_PUBLISH_SUBMIT_V1 = "youtube.publish.submit.v1"
YOUTUBE_PUBLISH_REFRESH_V1 = "youtube.publish.refresh.v1"


class _SessionFactory(Protocol):
    def __call__(self) -> Session: ...


class YouTubePublishSubmitV1Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: int = Field(gt=0)
    social_account_id: int = Field(gt=0)
    channel_id: str = Field(min_length=1, max_length=255)
    artifact_id: int = Field(gt=0)
    render_task_id: int = Field(gt=0)
    video_project_id: int = Field(gt=0)
    copy_matrix_id: int = Field(gt=0)
    publish_task_id: int = Field(gt=0)
    frozen_input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_expires_at: datetime


class YouTubePublishRefreshV1Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: int = Field(gt=0)
    social_account_id: int = Field(gt=0)
    publish_task_id: int = Field(gt=0)
    frozen_task_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    refresh_request_id: str = Field(min_length=16, max_length=128)


class _ContextYouTubeProvider:
    def __init__(self, context: ExecutionContext, provider: YouTubeProvider) -> None:
        self.context = context
        self.provider = provider

    async def refresh_access_token(self, refresh_token: str) -> OAuthTokens:
        self.context.before_provider_call(may_submit_external=False)
        return await self.provider.refresh_access_token(refresh_token)

    async def initiate_upload_session(self, **kwargs: object) -> str:
        self.context.before_provider_call(may_submit_external=False)
        return await self.provider.initiate_upload_session(**kwargs)

    async def upload_media(self, **kwargs: object) -> YouTubeUploadResult:
        self.context.before_provider_call(may_submit_external=True)
        return await self.provider.upload_media(**kwargs)

    async def get_video_status(self, **kwargs: object) -> YouTubeVideoStatus:
        self.context.before_provider_call(may_submit_external=False)
        return await self.provider.get_video_status(**kwargs)


class YouTubePublishSubmitV1Handler:
    job_type = YOUTUBE_PUBLISH_SUBMIT_V1
    input_schema = YouTubePublishSubmitV1Input

    def __init__(
        self,
        *,
        session_factory: _SessionFactory,
        provider: YouTubeProvider,
        settings: Settings,
        artifact_storage: VideoArtifactStorage,
    ) -> None:
        self.session_factory = session_factory
        self.provider = provider
        self.settings = settings
        self.artifact_storage = artifact_storage

    def execute(self, context: ExecutionContext, payload: BaseModel) -> HandlerResult:
        data = YouTubePublishSubmitV1Input.model_validate(payload)
        with self.session_factory() as session:
            service = YouTubePublishingService(
                session,
                self.settings,
                _ContextYouTubeProvider(context, self.provider),
                self.artifact_storage,
            )
            task = SocialRepository(session).get_publish_task(data.publish_task_id)
            if task is None or not _submit_identity_matches(service, task, data):
                return HandlerResult.failed("YOUTUBE_FROZEN_INPUT_MISMATCH")
            if task.status == "SUBMITTED" and task.provider_video_id:
                return _success(task)
            if task.status in {"UPLOADING", "SUBMIT_UNKNOWN"} or (
                task.resumable_session_ciphertext is not None
            ):
                _mark_submit_unknown(session, task, "upload_resume_forbidden")
                return HandlerResult.submit_unknown(
                    "YOUTUBE_UPLOAD_ALREADY_POSSIBLE", provider_name="youtube"
                )
            if task.status != "CREATED":
                return HandlerResult.failed("YOUTUBE_PUBLISH_STATE_INVALID")
            account = SocialRepository(session).get_account(task.social_account_id)
            if account is None:
                return HandlerResult.failed("YOUTUBE_ACCOUNT_MISSING")
            try:
                access_token = asyncio.run(service._access_token(account))
            except SocialAuthorizationError as exc:
                _mark_failed(session, task, exc.safe_error_code)
                return HandlerResult.failed("YOUTUBE_AUTHORIZATION_FAILED")
            try:
                verified, _ = service._verify_artifact(
                    task.product_id, task.artifact_id
                )
                session_uri = asyncio.run(
                    service._provider().initiate_upload_session(
                        access_token=access_token,
                        path=verified.path,
                        content_type=verified.content_type,
                        title=task.title,
                        description=task.description,
                        tags=task.tags,
                        made_for_kids=task.made_for_kids,
                    )
                )
            except AppError:
                _mark_failed(session, task, "artifact_validation_failed")
                return HandlerResult.failed("YOUTUBE_SESSION_INITIALIZATION_FAILED")
            except YouTubeProviderError as exc:
                _mark_failed(session, task, exc.safe_error_code)
                return HandlerResult.failed("YOUTUBE_SESSION_INITIALIZATION_FAILED")
            except Exception:
                _mark_failed(session, task, "upload_session_failed")
                return HandlerResult.failed("YOUTUBE_SESSION_INITIALIZATION_FAILED")

            try:
                task.resumable_session_ciphertext = TokenCipher(self.settings).encrypt(
                    session_uri
                )
                task.status = "UPLOADING"
                task.submitted_at = task.submitted_at or datetime.now(UTC)
                session.commit()
            except Exception:
                _mark_submit_unknown(session, task, "upload_session_persistence_failed")
                return HandlerResult.submit_unknown(
                    "YOUTUBE_SESSION_PERSISTENCE_UNKNOWN", provider_name="youtube"
                )
            try:
                result = asyncio.run(
                    service._provider().upload_media(
                        access_token=access_token,
                        path=verified.path,
                        content_type=verified.content_type,
                        session_uri=session_uri,
                    )
                )
                task.provider_video_id = result.video_id
                task.status = "SUBMITTED"
                task.uncertain = False
                task.safe_error_code = None
                session.commit()
            except Exception:
                _mark_submit_unknown(session, task, "upload_media_result_uncertain")
                return HandlerResult.submit_unknown(
                    "YOUTUBE_MEDIA_SUBMIT_UNKNOWN", provider_name="youtube"
                )
            return _success(task)


class YouTubePublishRefreshV1Handler:
    job_type = YOUTUBE_PUBLISH_REFRESH_V1
    input_schema = YouTubePublishRefreshV1Input

    def __init__(
        self,
        *,
        session_factory: _SessionFactory,
        provider: YouTubeProvider,
        settings: Settings,
        artifact_storage: VideoArtifactStorage,
    ) -> None:
        self.session_factory = session_factory
        self.provider = provider
        self.settings = settings
        self.artifact_storage = artifact_storage

    def execute(self, context: ExecutionContext, payload: BaseModel) -> HandlerResult:
        data = YouTubePublishRefreshV1Input.model_validate(payload)
        with self.session_factory() as session:
            task = SocialRepository(session).get_publish_task(data.publish_task_id)
            if (
                task is None
                or task.product_id != data.product_id
                or task.social_account_id != data.social_account_id
                or youtube_publish_task_digest(task) != data.frozen_task_digest
            ):
                return HandlerResult.failed("YOUTUBE_REFRESH_IDENTITY_MISMATCH")
            if task.status not in {"SUBMITTED", "PROCESSING"}:
                return HandlerResult.failed("YOUTUBE_REFRESH_STATE_INVALID")
            if not task.provider_video_id:
                return HandlerResult.failed("YOUTUBE_PROVIDER_ID_MISSING")
            service = YouTubePublishingService(
                session,
                self.settings,
                _ContextYouTubeProvider(context, self.provider),
                self.artifact_storage,
            )
            account = SocialRepository(session).get_account(task.social_account_id)
            if account is None or account.product_id != task.product_id:
                return HandlerResult.failed("YOUTUBE_REFRESH_ACCOUNT_MISMATCH")
            try:
                access_token = asyncio.run(service._access_token(account))
                result = asyncio.run(
                    service._provider().get_video_status(
                        access_token=access_token,
                        video_id=task.provider_video_id,
                    )
                )
            except (SocialAuthorizationError, YouTubeProviderError, AppError):
                return HandlerResult.failed("YOUTUBE_STATUS_QUERY_FAILED")
            task.status = result.status
            task.safe_error_code = result.safe_error_code
            task.uncertain = False
            if result.status in {"SUCCEEDED", "FAILED"}:
                task.completed_at = datetime.now(UTC)
            session.commit()
            return _success(task)


def youtube_publish_task_digest(task: PublishTask) -> str:
    payload = {
        "contract": "youtube-publish-refresh-v1",
        "publish_task_id": task.id,
        "product_id": task.product_id,
        "social_account_id": task.social_account_id,
        "artifact_id": task.artifact_id,
        "provider_video_id": task.provider_video_id,
        "status": task.status,
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _submit_identity_matches(
    service: YouTubePublishingService,
    task: PublishTask,
    data: YouTubePublishSubmitV1Input,
) -> bool:
    if (
        task.product_id != data.product_id
        or task.social_account_id != data.social_account_id
        or task.artifact_id != data.artifact_id
        or task.request_digest != data.frozen_input_digest
        or task.preflight_digest != data.preflight_digest
        or data.preflight_digest
        != _preflight_digest(data.frozen_input_digest, data.preflight_expires_at)
    ):
        return False
    metadata = YouTubePublishingMetadata(
        social_account_id=task.social_account_id,
        artifact_id=task.artifact_id,
        title=task.title,
        description=task.description,
        tags=task.tags,
        privacy_status="private",
        made_for_kids=task.made_for_kids,
        synthetic_media=True,
        notify_subscribers=False,
    )
    try:
        current = service.preflight(task.product_id, metadata)
    except AppError:
        return False
    return (
        current.ready
        and current.input_digest == data.frozen_input_digest
        and current.channel_id == data.channel_id
        and current.render_task_id == data.render_task_id
        and current.video_project_id == data.video_project_id
        and current.copy_matrix_id == data.copy_matrix_id
    )


def _preflight_digest(input_digest: str, expires_at: datetime) -> str:
    normalized = (
        expires_at.replace(tzinfo=UTC)
        if expires_at.tzinfo is None
        else expires_at.astimezone(UTC)
    )
    payload = {
        "contract": "youtube-private-preflight-v1",
        "input_digest": input_digest,
        "expires_at": normalized.isoformat(),
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _mark_failed(session: Session, task: PublishTask, code: str) -> None:
    task.status = "FAILED"
    task.uncertain = False
    task.safe_error_code = code
    task.completed_at = datetime.now(UTC)
    session.commit()


def _mark_submit_unknown(session: Session, task: PublishTask, code: str) -> None:
    task_id = task.id
    session.rollback()
    persisted = session.get(PublishTask, task_id)
    if persisted is None:
        return
    persisted.status = "SUBMIT_UNKNOWN"
    persisted.uncertain = True
    persisted.safe_error_code = code
    session.commit()


def _success(task: PublishTask) -> HandlerResult:
    return HandlerResult.succeeded(
        provider_name="youtube",
        result_entity_type="publish_task",
        result_entity_id=task.id,
    )

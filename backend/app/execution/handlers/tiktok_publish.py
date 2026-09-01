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
from app.models.social import PublishTask
from app.providers.tiktok_provider import TikTokProvider
from app.repositories.social import SocialRepository
from app.schemas.social import TikTokPublishingMetadata
from app.services.social_security import TokenCipher
from app.services.tiktok_media_probe import TikTokMediaProbe
from app.services.tiktok_publish_preflight import (
    TikTokPublishPreflightService,
    preflight_digest,
)
from app.services.tiktok_publish_service import (
    TikTokPublishService,
    tiktok_refresh_task_digest,
)
from app.services.video_artifact_storage import VideoArtifactStorage

TIKTOK_PUBLISH_CREATOR_INFO_V1 = "tiktok.publish.creator_info.v1"
TIKTOK_PUBLISH_SUBMIT_V1 = "tiktok.publish.submit.v1"
TIKTOK_PUBLISH_REFRESH_V1 = "tiktok.publish.refresh.v1"
CHUNK_SIZE = 10 * 1024 * 1024


class _SessionFactory(Protocol):
    def __call__(self) -> Session: ...


class _ContextTikTokProvider:
    def __init__(self, context: ExecutionContext, provider: TikTokProvider) -> None:
        self.context = context
        self.provider = provider

    async def refresh_access_token(self, refresh_token: str):
        self.context.before_provider_call(may_submit_external=False)
        return await self.provider.refresh_access_token(refresh_token)


class TikTokCreatorInfoV1Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: int = Field(gt=0)
    social_account_id: int = Field(gt=0)
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_id: str = Field(min_length=16, max_length=128)
    provider_account_id: str = Field(min_length=1, max_length=255)


class TikTokSubmitV1Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: int = Field(gt=0)
    publish_task_id: int = Field(gt=0)
    creator_info_snapshot_id: int = Field(gt=0)
    frozen_input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight_expires_at: datetime
    metadata: TikTokPublishingMetadata


class TikTokRefreshV1Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: int = Field(gt=0)
    publish_task_id: int = Field(gt=0)
    social_account_id: int = Field(gt=0)
    artifact_id: int = Field(gt=0)
    provider_publish_id: str = Field(min_length=1, max_length=255)
    frozen_task_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    refresh_request_id: str = Field(min_length=16, max_length=128)


class TikTokCreatorInfoV1Handler:
    job_type = TIKTOK_PUBLISH_CREATOR_INFO_V1
    input_schema = TikTokCreatorInfoV1Input

    def __init__(
        self,
        *,
        session_factory: _SessionFactory,
        provider: TikTokProvider,
        settings: Settings,
        **_: object,
    ) -> None:
        self.session_factory, self.provider, self.settings = (
            session_factory,
            provider,
            settings,
        )

    def execute(self, context: ExecutionContext, payload: BaseModel) -> HandlerResult:
        data = TikTokCreatorInfoV1Input.model_validate(payload)
        with self.session_factory() as session:
            account = SocialRepository(session).get_account(data.social_account_id)
            if (
                account is None
                or account.product_id != data.product_id
                or account.platform != "tiktok"
                or account.connection_status != "CONNECTED"
                or account.provider_account_id != data.provider_account_id
            ):
                return HandlerResult.failed("TIKTOK_CREATOR_IDENTITY_MISMATCH")
            service = TikTokPublishService(session, self.settings)
            try:
                token = asyncio.run(
                    service.access_token(
                        account, _ContextTikTokProvider(context, self.provider)
                    )
                )
                context.before_provider_call(may_submit_external=False)
                info = asyncio.run(self.provider.query_creator_info(access_token=token))
                snapshot = service.create_snapshot(
                    product_id=data.product_id,
                    account=account,
                    info=info,
                    request_digest=data.request_digest,
                )
            except (LeaseLostError, WorkerStopRequested):
                raise
            except Exception:
                return HandlerResult.failed("TIKTOK_CREATOR_INFO_FAILED")
            return HandlerResult.succeeded(
                provider_name="tiktok",
                result_entity_type="tiktok_creator_info_snapshot",
                result_entity_id=snapshot.id,
            )


class TikTokSubmitV1Handler:
    job_type = TIKTOK_PUBLISH_SUBMIT_V1
    input_schema = TikTokSubmitV1Input

    def __init__(
        self,
        *,
        session_factory: _SessionFactory,
        provider: TikTokProvider,
        settings: Settings,
        artifact_storage: VideoArtifactStorage,
        media_probe: TikTokMediaProbe,
    ) -> None:
        self.session_factory, self.provider, self.settings = (
            session_factory,
            provider,
            settings,
        )
        self.storage, self.media_probe = artifact_storage, media_probe

    def execute(self, context: ExecutionContext, payload: BaseModel) -> HandlerResult:
        data = TikTokSubmitV1Input.model_validate(payload)
        with self.session_factory() as session:
            task = SocialRepository(session).get_publish_task(data.publish_task_id)
            if task is None:
                return HandlerResult.failed("TIKTOK_FROZEN_INPUT_MISMATCH")
            if (
                task.product_id != data.product_id
                or task.platform != "tiktok"
                or task.request_digest != data.frozen_input_digest
            ):
                _failed(session, task, "tiktok_frozen_input_mismatch")
                return HandlerResult.failed("TIKTOK_FROZEN_INPUT_MISMATCH")
            if (
                task.provider_publish_id
                or task.resumable_session_ciphertext
                or task.status in {"UPLOADING", "PROCESSING", "SUBMIT_UNKNOWN"}
            ):
                _unknown(session, task, "tiktok_submit_already_possible")
                return HandlerResult.submit_unknown(
                    "TIKTOK_SUBMIT_ALREADY_POSSIBLE", provider_name="tiktok"
                )
            try:
                frozen = TikTokPublishPreflightService(
                    session, self.settings, self.storage, self.media_probe
                ).freeze(data.product_id, data.metadata)
                if (
                    frozen.input_digest != data.frozen_input_digest
                    or frozen.creator_info_snapshot_id != data.creator_info_snapshot_id
                    or task.social_account_id != data.metadata.social_account_id
                    or task.artifact_id != data.metadata.artifact_id
                    or task.preflight_digest != data.preflight_digest
                    or task.title != data.metadata.title
                    or task.description != data.metadata.description
                    or task.tags != data.metadata.tags
                    or task.privacy_status != data.metadata.privacy_status
                    or task.disable_comment != data.metadata.disable_comment
                    or task.disable_duet != data.metadata.disable_duet
                    or task.disable_stitch != data.metadata.disable_stitch
                    or task.brand_content_toggle != data.metadata.brand_content_toggle
                    or task.brand_organic_toggle != data.metadata.brand_organic_toggle
                    or preflight_digest(
                        data.frozen_input_digest, data.preflight_expires_at
                    )
                    != data.preflight_digest
                ):
                    raise AppError("frozen mismatch", 409)
                account = SocialRepository(session).get_account(
                    task.social_account_id
                )
                if account is None:
                    raise AppError("account missing", 409)
                token = asyncio.run(
                    TikTokPublishService(session, self.settings).access_token(
                        account, _ContextTikTokProvider(context, self.provider)
                    )
                )
            except AppError:
                _failed(session, task, "tiktok_submit_validation_failed")
                return HandlerResult.failed("TIKTOK_SUBMIT_VALIDATION_FAILED")
            try:
                total_chunks = max(
                    1, (frozen.size_bytes + CHUNK_SIZE - 1) // CHUNK_SIZE
                )
                chunk_size = frozen.size_bytes if total_chunks == 1 else CHUNK_SIZE
                context.before_provider_call(may_submit_external=True)
                initiated = asyncio.run(
                    self.provider.initialize_direct_post(
                        access_token=token,
                        caption=frozen.caption,
                        privacy_level=task.privacy_status,
                        disable_comment=task.disable_comment,
                        disable_duet=task.disable_duet,
                        disable_stitch=task.disable_stitch,
                        brand_content_toggle=task.brand_content_toggle,
                        brand_organic_toggle=task.brand_organic_toggle,
                        size_bytes=frozen.size_bytes,
                        chunk_size=chunk_size,
                        total_chunks=total_chunks,
                    )
                )
                task.provider_publish_id = initiated.publish_id
                task.resumable_session_ciphertext = TokenCipher(self.settings).encrypt(
                    initiated.upload_url
                )
                task.status = "UPLOADING"
                task.submitted_at = datetime.now(UTC)
                session.commit()
                with frozen.verified.path.open("rb") as stream:
                    start = 0
                    while start < frozen.size_bytes:
                        chunk = stream.read(chunk_size)
                        context.before_provider_call(may_submit_external=True)
                        asyncio.run(
                            self.provider.upload_video_chunk(
                                upload_url=initiated.upload_url,
                                content=chunk,
                                start=start,
                                end=start + len(chunk) - 1,
                                total=frozen.size_bytes,
                                content_type=frozen.content_type,
                            )
                        )
                        start += len(chunk)
                task.status = "PROCESSING"
                task.uncertain = False
                task.safe_error_code = None
                session.commit()
                return _success(task)
            except (LeaseLostError, WorkerStopRequested):
                _unknown(session, task, "tiktok_worker_interrupted_after_submit")
                raise
            except Exception:
                _unknown(session, task, "tiktok_submit_result_uncertain")
                return HandlerResult.submit_unknown(
                    "TIKTOK_SUBMIT_UNKNOWN", provider_name="tiktok"
                )


class TikTokRefreshV1Handler:
    job_type = TIKTOK_PUBLISH_REFRESH_V1
    input_schema = TikTokRefreshV1Input

    def __init__(
        self,
        *,
        session_factory: _SessionFactory,
        provider: TikTokProvider,
        settings: Settings,
        **_: object,
    ) -> None:
        self.session_factory, self.provider, self.settings = (
            session_factory,
            provider,
            settings,
        )

    def execute(self, context: ExecutionContext, payload: BaseModel) -> HandlerResult:
        data = TikTokRefreshV1Input.model_validate(payload)
        with self.session_factory() as session:
            task = SocialRepository(session).get_publish_task(data.publish_task_id)
            if (
                task is None
                or task.product_id != data.product_id
                or task.platform != "tiktok"
                or task.social_account_id != data.social_account_id
                or task.artifact_id != data.artifact_id
                or task.status != "PROCESSING"
                or not task.provider_publish_id
                or task.provider_publish_id != data.provider_publish_id
                or tiktok_refresh_task_digest(task) != data.frozen_task_digest
            ):
                return HandlerResult.failed("TIKTOK_REFRESH_IDENTITY_MISMATCH")
            account = SocialRepository(session).get_account(task.social_account_id)
            try:
                token = asyncio.run(
                    TikTokPublishService(session, self.settings).access_token(
                        account, _ContextTikTokProvider(context, self.provider)
                    )
                )
                context.before_provider_call(may_submit_external=False)
                status = asyncio.run(
                    self.provider.fetch_publish_status(
                        access_token=token, publish_id=task.provider_publish_id
                    )
                )
            except (LeaseLostError, WorkerStopRequested):
                raise
            except Exception:
                return HandlerResult.failed("TIKTOK_STATUS_QUERY_FAILED")
            if status.status == "PUBLISH_COMPLETE":
                task.status = "SUCCEEDED"
                task.completed_at = datetime.now(UTC)
            elif status.status == "FAILED":
                task.status = "FAILED"
                task.completed_at = datetime.now(UTC)
                task.safe_error_code = "tiktok_provider_failed"
            else:
                task.status = "PROCESSING"
            session.commit()
            return _success(task)


def _success(task: PublishTask) -> HandlerResult:
    return HandlerResult.succeeded(
        provider_name="tiktok",
        result_entity_type="publish_task",
        result_entity_id=task.id,
    )


def _failed(session: Session, task: PublishTask, code: str) -> None:
    task.status = "FAILED"
    task.safe_error_code = code
    task.uncertain = False
    task.completed_at = datetime.now(UTC)
    session.commit()


def _unknown(session: Session, task: PublishTask, code: str) -> None:
    task_id = task.id
    try:
        task.status = "SUBMIT_UNKNOWN"
        task.safe_error_code = code
        task.uncertain = True
        session.commit()
    except Exception:
        session.rollback()
        recovered = session.get(PublishTask, task_id)
        workspace_id = SocialRepository(session).workspace_id
        if recovered is None or (
            workspace_id is not None and recovered.workspace_id != workspace_id
        ):
            return
        recovered.status = "SUBMIT_UNKNOWN"
        recovered.safe_error_code = code
        recovered.uncertain = True
        try:
            session.commit()
        except Exception:
            session.rollback()

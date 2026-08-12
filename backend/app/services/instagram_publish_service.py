from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.models import PublishTask, SocialAccount
from app.schemas.social import (
    InstagramFinalizePreflightRead,
    InstagramPublishingMetadata,
)
from app.services.instagram_media_probe import InstagramMediaProbe
from app.services.instagram_publish_preflight import (
    INSTAGRAM_PREFLIGHT_LIFETIME,
    FrozenInstagramPublishInput,
    InstagramPublishPreflightService,
    preflight_digest,
)
from app.services.social_security import TokenCipher
from app.services.video_artifact_storage import VideoArtifactStorage


class InstagramPublishService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        artifact_storage: VideoArtifactStorage,
        media_probe: InstagramMediaProbe,
    ) -> None:
        self.session = session
        self.settings = settings
        self.preflight_service = InstagramPublishPreflightService(
            session, settings, artifact_storage, media_probe
        )

    def get_task(self, task_id: int, product_id: int) -> PublishTask:
        task = self.session.get(PublishTask, task_id)
        if (
            task is None
            or task.product_id != product_id
            or task.platform != "instagram"
        ):
            raise AppError("Instagram PublishTask not found for Product", 404)
        return task

    def account(self, task: PublishTask) -> SocialAccount:
        account = self.session.get(SocialAccount, task.social_account_id)
        if (
            account is None
            or account.product_id != task.product_id
            or account.platform != "instagram"
            or account.connection_status != "CONNECTED"
        ):
            raise AppError("Instagram account identity is invalid", 409)
        return account

    def access_token(self, account: SocialAccount) -> str:
        if not account.access_token_ciphertext:
            raise AppError("Instagram authorization is unavailable", 409)
        expires_at = _as_utc(account.token_expires_at)
        if expires_at is not None and expires_at <= datetime.now(UTC):
            raise AppError("Instagram authorization has expired", 409)
        return TokenCipher(self.settings).decrypt(account.access_token_ciphertext)

    def freeze_task(self, task: PublishTask) -> FrozenInstagramPublishInput:
        metadata = InstagramPublishingMetadata(
            social_account_id=task.social_account_id,
            artifact_id=task.artifact_id,
            title=task.title,
            description=task.description,
            tags=task.tags,
            privacy_status="public",
            made_for_kids=False,
            synthetic_media=True,
            notify_subscribers=False,
            share_to_feed=task.share_to_feed,
        )
        return self.preflight_service.freeze(task.product_id, metadata)

    def finalize_preflight(
        self,
        task_id: int,
        product_id: int,
        *,
        expires_at: datetime | None = None,
    ) -> InstagramFinalizePreflightRead:
        self._require_enabled()
        task = self.get_task(task_id, product_id)
        account = self.account(task)
        if task.status != "READY_TO_PUBLISH" or not task.provider_container_id:
            raise AppError("Instagram PublishTask is not ready for public publish", 409)
        if not account.access_token_ciphertext:
            raise AppError("Instagram authorization is unavailable", 409)
        expiry = _as_utc(expires_at or datetime.now(UTC) + INSTAGRAM_PREFLIGHT_LIFETIME)
        now = datetime.now(UTC)
        if expiry <= now or expiry > now + INSTAGRAM_PREFLIGHT_LIFETIME:
            raise AppError("Instagram finalize Preflight expiry is invalid", 409)
        digest = instagram_finalize_input_digest(task, account)
        return InstagramFinalizePreflightRead(
            product_id=task.product_id,
            social_account_id=task.social_account_id,
            publish_task_id=task.id,
            input_digest=digest,
            preflight_digest=instagram_finalize_preflight_digest(digest, expiry),
            expires_at=expiry,
        )

    def _require_enabled(self) -> None:
        if not self.settings.enable_instagram_publishing:
            raise AppError("Instagram publishing is disabled by the server", 503)


def instagram_job_input_digest(preflight_input_digest: str, task_id: int) -> str:
    return _digest(
        {
            "contract": "instagram-reel-submit-job-v1",
            "preflight_input_digest": preflight_input_digest,
            "publish_task_id": task_id,
        }
    )


def instagram_refresh_task_digest(task: PublishTask) -> str:
    return _digest(
        {
            "contract": "instagram-reel-refresh-v1",
            "publish_task_id": task.id,
            "product_id": task.product_id,
            "social_account_id": task.social_account_id,
            "artifact_id": task.artifact_id,
            "provider_container_id": task.provider_container_id,
            "request_digest": task.request_digest,
        }
    )


def instagram_finalize_input_digest(task: PublishTask, account: SocialAccount) -> str:
    return _digest(
        {
            "contract": "instagram-reel-finalize-v1",
            "publish_task_id": task.id,
            "product_id": task.product_id,
            "social_account_id": task.social_account_id,
            "professional_account_id": account.provider_account_id,
            "artifact_id": task.artifact_id,
            "provider_container_id": task.provider_container_id,
            "request_digest": task.request_digest,
            "status": "READY_TO_PUBLISH",
        }
    )


def instagram_finalize_preflight_digest(input_digest: str, expires_at: datetime) -> str:
    return _digest(
        {
            "contract": "instagram-reel-finalize-preflight-v1",
            "input_digest": input_digest,
            "expires_at": _as_utc(expires_at).isoformat(),
        }
    )


def validate_submit_preflight_digest(
    input_digest: str, digest: str, expires_at: datetime
) -> bool:
    return preflight_digest(input_digest, expires_at) == digest


def _digest(payload: object) -> str:
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)

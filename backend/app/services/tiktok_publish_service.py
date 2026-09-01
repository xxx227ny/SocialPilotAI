from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.models.social import PublishTask, SocialAccount, TikTokCreatorInfoSnapshot
from app.providers.tiktok_provider import (
    TIKTOK_SCOPES,
    TikTokProvider,
    TikTokProviderError,
)
from app.repositories.social import SocialRepository
from app.schemas.social import PublishTaskRead, TikTokCreatorInfoSnapshotRead
from app.services.social_security import TokenCipher


class TikTokPublishService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session, self.settings = session, settings
        self.social = SocialRepository(session)

    def get_snapshot(
        self, snapshot_id: int, product_id: int, social_account_id: int
    ) -> TikTokCreatorInfoSnapshotRead:
        snapshot = self.social.get_tiktok_creator_snapshot(snapshot_id)
        account = self.social.get_account(social_account_id)
        if (
            snapshot is None
            or snapshot.product_id != product_id
            or snapshot.social_account_id != social_account_id
            or account is None
            or account.product_id != product_id
            or account.platform != "tiktok"
        ):
            raise AppError("TikTok creator snapshot not found", 404)
        return TikTokCreatorInfoSnapshotRead.model_validate(snapshot)

    def get_task(self, task_id: int, product_id: int) -> PublishTaskRead:
        task = SocialRepository(self.session).get_publish_task(task_id)
        if task is None or task.product_id != product_id or task.platform != "tiktok":
            raise AppError("TikTok PublishTask not found", 404)
        return PublishTaskRead.model_validate(task)

    async def access_token(
        self, account: SocialAccount, provider: TikTokProvider
    ) -> str:
        if account.connection_status != "CONNECTED" or set(account.scopes) != set(
            TIKTOK_SCOPES
        ):
            raise AppError("TikTok authorization is invalid", 409)
        cipher = TokenCipher(self.settings)
        try:
            token = cipher.decrypt(account.access_token_ciphertext or "")
        except AppError:
            raise AppError("TikTok token unavailable", 409) from None
        expiry = _utc(account.token_expires_at) if account.token_expires_at else None
        if expiry is not None and expiry > datetime.now(UTC) + timedelta(minutes=2):
            return token
        if not account.refresh_token_ciphertext or (
            account.refresh_token_expires_at
            and _utc(account.refresh_token_expires_at) <= datetime.now(UTC)
        ):
            account.connection_status = "EXPIRED"
            self.session.commit()
            raise AppError("TikTok reauthorization is required", 409)
        try:
            refreshed = await provider.refresh_access_token(
                cipher.decrypt(account.refresh_token_ciphertext)
            )
        except (AppError, TikTokProviderError):
            account.connection_status = "EXPIRED"
            self.session.commit()
            raise AppError("TikTok token refresh failed", 409) from None
        if refreshed.open_id != account.provider_account_id or set(
            refreshed.scopes
        ) != set(TIKTOK_SCOPES):
            account.connection_status = "EXPIRED"
            self.session.commit()
            raise AppError("TikTok refreshed identity mismatch", 409)
        account.access_token_ciphertext = cipher.encrypt(refreshed.access_token)
        account.refresh_token_ciphertext = cipher.encrypt(refreshed.refresh_token)
        account.token_expires_at = refreshed.access_token_expires_at
        account.refresh_token_expires_at = refreshed.refresh_token_expires_at
        self.session.commit()
        return refreshed.access_token

    def create_snapshot(
        self,
        *,
        product_id: int,
        account: SocialAccount,
        info: object,
        request_digest: str,
    ) -> TikTokCreatorInfoSnapshot:
        now = datetime.now(UTC)
        identity = hashlib.sha256(
            json.dumps(
                {
                    "open_id": account.provider_account_id,
                    "username": info.creator_username,
                    "nickname": info.creator_nickname,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        snapshot = TikTokCreatorInfoSnapshot(
            workspace_id=self.social.workspace_id,
            product_id=product_id,
            social_account_id=account.id,
            request_digest=request_digest,
            provider_identity_digest=identity,
            creator_username=info.creator_username,
            creator_nickname=info.creator_nickname,
            privacy_level_options=list(info.privacy_level_options),
            comment_disabled=info.comment_disabled,
            duet_disabled=info.duet_disabled,
            stitch_disabled=info.stitch_disabled,
            max_video_post_duration_sec=info.max_video_post_duration_sec,
            fetched_at=now,
            expires_at=now + timedelta(minutes=10),
            created_at=now,
        )
        self.session.add(snapshot)
        self.session.commit()
        self.session.refresh(snapshot)
        return snapshot


def tiktok_refresh_task_digest(task: PublishTask) -> str:
    payload = {
        "contract": "tiktok-publish-refresh-v1",
        "task_id": task.id,
        "product_id": task.product_id,
        "account_id": task.social_account_id,
        "artifact_id": task.artifact_id,
        "provider_publish_id": task.provider_publish_id,
        "status": task.status,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)

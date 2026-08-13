from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import OAuthSession, PublishTask, SocialAccount
from app.models.social import TikTokCreatorInfoSnapshot


class SocialRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_accounts(self, product_id: int) -> list[SocialAccount]:
        statement = (
            select(SocialAccount)
            .where(SocialAccount.product_id == product_id)
            .order_by(SocialAccount.id)
        )
        return list(self.session.scalars(statement).all())

    def get_account(self, account_id: int) -> SocialAccount | None:
        return self.session.get(SocialAccount, account_id)

    def get_account_by_channel(
        self, product_id: int, channel_id: str
    ) -> SocialAccount | None:
        return self.session.scalar(
            select(SocialAccount).where(
                SocialAccount.product_id == product_id,
                SocialAccount.platform == "youtube",
                SocialAccount.provider_account_id == channel_id,
            )
        )

    def get_account_by_provider_identity(
        self, product_id: int, platform: str, provider_account_id: str
    ) -> SocialAccount | None:
        return self.session.scalar(
            select(SocialAccount).where(
                SocialAccount.product_id == product_id,
                SocialAccount.platform == platform,
                SocialAccount.provider_account_id == provider_account_id,
            )
        )

    def get_oauth_session(self, state_digest: str) -> OAuthSession | None:
        return self.session.scalar(
            select(OAuthSession).where(OAuthSession.state_digest == state_digest)
        )

    def get_publish_task(self, task_id: int) -> PublishTask | None:
        return self.session.get(PublishTask, task_id)

    def get_publish_task_by_key(self, key: str) -> PublishTask | None:
        return self.session.scalar(
            select(PublishTask).where(PublishTask.idempotency_key == key)
        )

    def list_publish_tasks(self, product_id: int) -> list[PublishTask]:
        statement = (
            select(PublishTask)
            .where(PublishTask.product_id == product_id)
            .order_by(PublishTask.created_at.desc(), PublishTask.id.desc())
        )
        return list(self.session.scalars(statement).all())

    def get_tiktok_creator_snapshot(
        self, snapshot_id: int
    ) -> TikTokCreatorInfoSnapshot | None:
        return self.session.get(TikTokCreatorInfoSnapshot, snapshot_id)

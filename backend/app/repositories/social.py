from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution.workspace_context import current_execution_workspace_id
from app.models import OAuthSession, Product, PublishTask, SocialAccount
from app.models.social import TikTokCreatorInfoSnapshot


class SocialRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    @property
    def workspace_id(self) -> int | None:
        value = self.session.info.get("workspace_id")
        if value is None:
            value = current_execution_workspace_id()
        return int(value) if value is not None else None

    def _workspace_condition(self, model: type) -> object | None:
        workspace_id = self.workspace_id
        if workspace_id is None:
            return None
        return model.workspace_id == workspace_id

    def scoped_idempotency_key(self, key: str) -> str:
        workspace_id = self.workspace_id
        if workspace_id is None:
            return key
        scoped = f"workspace:{workspace_id}:{key}"
        if len(scoped) <= 200:
            return scoped
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return f"workspace:{workspace_id}:sha256:{digest}"

    def list_accounts(self, product_id: int) -> list[SocialAccount]:
        statement = (
            select(SocialAccount)
            .where(SocialAccount.product_id == product_id)
            .order_by(SocialAccount.id)
        )
        condition = self._workspace_condition(SocialAccount)
        if condition is not None:
            statement = statement.where(condition)
        return list(self.session.scalars(statement).all())

    def list_workspace_accounts(self) -> list[tuple[SocialAccount, str]]:
        statement = (
            select(SocialAccount, Product.name)
            .join(Product, Product.id == SocialAccount.product_id)
            .order_by(SocialAccount.updated_at.desc(), SocialAccount.id.desc())
        )
        condition = self._workspace_condition(SocialAccount)
        if condition is not None:
            statement = statement.where(
                condition,
                Product.workspace_id == self.workspace_id,
            )
        return [
            (account, product_name)
            for account, product_name in self.session.execute(statement).all()
        ]

    def get_account(self, account_id: int) -> SocialAccount | None:
        statement = select(SocialAccount).where(SocialAccount.id == account_id)
        condition = self._workspace_condition(SocialAccount)
        if condition is not None:
            statement = statement.where(condition)
        return self.session.scalar(statement)

    def get_account_by_channel(
        self, product_id: int, channel_id: str
    ) -> SocialAccount | None:
        statement = select(SocialAccount).where(
            SocialAccount.product_id == product_id,
            SocialAccount.platform == "youtube",
            SocialAccount.provider_account_id == channel_id,
        )
        condition = self._workspace_condition(SocialAccount)
        if condition is not None:
            statement = statement.where(condition)
        return self.session.scalar(statement)

    def get_account_by_provider_identity(
        self, product_id: int, platform: str, provider_account_id: str
    ) -> SocialAccount | None:
        statement = select(SocialAccount).where(
            SocialAccount.product_id == product_id,
            SocialAccount.platform == platform,
            SocialAccount.provider_account_id == provider_account_id,
        )
        condition = self._workspace_condition(SocialAccount)
        if condition is not None:
            statement = statement.where(condition)
        return self.session.scalar(statement)

    def get_oauth_session(self, state_digest: str) -> OAuthSession | None:
        statement = select(OAuthSession).where(
            OAuthSession.state_digest == state_digest
        )
        condition = self._workspace_condition(OAuthSession)
        if condition is not None:
            statement = statement.where(condition)
        return self.session.scalar(statement)

    def get_publish_task(self, task_id: int) -> PublishTask | None:
        statement = select(PublishTask).where(PublishTask.id == task_id)
        condition = self._workspace_condition(PublishTask)
        if condition is not None:
            statement = statement.where(condition)
        return self.session.scalar(statement)

    def get_publish_task_by_key(self, key: str) -> PublishTask | None:
        statement = select(PublishTask).where(PublishTask.idempotency_key == key)
        condition = self._workspace_condition(PublishTask)
        if condition is not None:
            statement = statement.where(condition)
        return self.session.scalar(statement)

    def list_publish_tasks(self, product_id: int) -> list[PublishTask]:
        statement = (
            select(PublishTask)
            .where(PublishTask.product_id == product_id)
            .order_by(PublishTask.created_at.desc(), PublishTask.id.desc())
        )
        condition = self._workspace_condition(PublishTask)
        if condition is not None:
            statement = statement.where(condition)
        return list(self.session.scalars(statement).all())

    def get_tiktok_creator_snapshot(
        self, snapshot_id: int
    ) -> TikTokCreatorInfoSnapshot | None:
        statement = select(TikTokCreatorInfoSnapshot).where(
            TikTokCreatorInfoSnapshot.id == snapshot_id
        )
        condition = self._workspace_condition(TikTokCreatorInfoSnapshot)
        if condition is not None:
            statement = statement.where(condition)
        return self.session.scalar(statement)

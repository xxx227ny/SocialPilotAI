from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.product import utc_now

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.video_render_artifact import VideoRenderArtifact


class SocialAccount(Base):
    __tablename__ = "social_accounts"
    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "platform",
            "provider_account_id",
            name="uq_social_account_product_platform_provider",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    provider_account_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    access_token_ciphertext: Mapped[str | None] = mapped_column(Text)
    refresh_token_ciphertext: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refresh_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    connection_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="CONNECTED", index=True
    )
    encryption_key_id: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    product: Mapped[Product] = relationship()
    publish_tasks: Mapped[list[PublishTask]] = relationship(
        back_populates="social_account", cascade="all, delete-orphan"
    )


class OAuthSession(Base):
    __tablename__ = "oauth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(30), nullable=False)
    state_digest: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    browser_session_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    pkce_verifier_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    redirect_path: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class PublishTask(Base):
    __tablename__ = "publish_tasks"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_publish_task_idempotency"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    social_account_id: Mapped[int] = mapped_column(
        ForeignKey("social_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    artifact_id: Mapped[int] = mapped_column(
        ForeignKey("video_render_artifacts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    platform: Mapped[str] = mapped_column(String(30), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    preflight_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    privacy_status: Mapped[str] = mapped_column(String(20), nullable=False)
    made_for_kids: Mapped[bool] = mapped_column(Boolean, nullable=False)
    synthetic_media: Mapped[bool] = mapped_column(Boolean, nullable=False)
    notify_subscribers: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="CREATED", index=True
    )
    provider_video_id: Mapped[str | None] = mapped_column(String(255), index=True)
    provider_container_id: Mapped[str | None] = mapped_column(String(255), index=True)
    resumable_session_ciphertext: Mapped[str | None] = mapped_column(Text)
    share_to_feed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    safe_error_code: Mapped[str | None] = mapped_column(String(100))
    uncertain: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    social_account: Mapped[SocialAccount] = relationship(back_populates="publish_tasks")
    artifact: Mapped[VideoRenderArtifact] = relationship()

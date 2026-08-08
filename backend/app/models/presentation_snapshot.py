from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, event
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.product import utc_now


class PresentationSnapshot(Base):
    """Immutable, self-contained evidence captured from explicit source IDs."""

    __tablename__ = "presentation_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    digest: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    product_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    marketing_brief_id: Mapped[int | None] = mapped_column(Integer)
    marketing_strategy_id: Mapped[int | None] = mapped_column(Integer)
    copy_matrix_id: Mapped[int | None] = mapped_column(Integer)
    video_project_id: Mapped[int | None] = mapped_column(Integer)
    render_task_id: Mapped[int | None] = mapped_column(Integer)
    artifact_id: Mapped[int | None] = mapped_column(Integer)
    publish_task_id: Mapped[int | None] = mapped_column(Integer)
    campaign_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    missing_sections: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    snapshot_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    artifact_sha256: Mapped[str | None] = mapped_column(String(64))
    artifact_snapshot_path: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


def _reject_snapshot_mutation(*_: object, **__: object) -> None:
    raise ValueError("PresentationSnapshot records are immutable")


event.listen(PresentationSnapshot, "before_update", _reject_snapshot_mutation)
event.listen(PresentationSnapshot, "before_delete", _reject_snapshot_mutation)

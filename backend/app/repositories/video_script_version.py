from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.video_script_version import VideoScriptVersion


class VideoScriptVersionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, variant_id: int, version_id: int) -> VideoScriptVersion | None:
        return self.session.scalar(
            select(VideoScriptVersion)
            .options(selectinload(VideoScriptVersion.scenes))
            .where(
                VideoScriptVersion.id == version_id,
                VideoScriptVersion.batch_video_variant_id == variant_id,
            )
        )

    def get_by_idempotency(
        self, variant_id: int, key: str
    ) -> VideoScriptVersion | None:
        return self.session.scalar(
            select(VideoScriptVersion)
            .options(selectinload(VideoScriptVersion.scenes))
            .where(
                VideoScriptVersion.batch_video_variant_id == variant_id,
                VideoScriptVersion.idempotency_key == key,
            )
        )

    def list(self, variant_id: int) -> list[VideoScriptVersion]:
        return list(
            self.session.scalars(
                select(VideoScriptVersion)
                .options(selectinload(VideoScriptVersion.scenes))
                .where(VideoScriptVersion.batch_video_variant_id == variant_id)
                .order_by(VideoScriptVersion.version_number.asc())
            ).all()
        )

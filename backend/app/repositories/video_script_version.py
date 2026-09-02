from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import BatchVideoVariant
from app.models.video_script_version import VideoScriptVersion
from app.repositories.workspace_scope import scope_to_owned_products


class VideoScriptVersionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, variant_id: int, version_id: int) -> VideoScriptVersion | None:
        owned_variants = scope_to_owned_products(
            select(BatchVideoVariant.id), BatchVideoVariant, self.session
        )
        return self.session.scalar(
            select(VideoScriptVersion)
            .options(selectinload(VideoScriptVersion.scenes))
            .where(
                VideoScriptVersion.id == version_id,
                VideoScriptVersion.batch_video_variant_id == variant_id,
                VideoScriptVersion.batch_video_variant_id.in_(owned_variants),
            )
        )

    def get_by_idempotency(
        self, variant_id: int, key: str
    ) -> VideoScriptVersion | None:
        owned_variants = scope_to_owned_products(
            select(BatchVideoVariant.id), BatchVideoVariant, self.session
        )
        return self.session.scalar(
            select(VideoScriptVersion)
            .options(selectinload(VideoScriptVersion.scenes))
            .where(
                VideoScriptVersion.batch_video_variant_id == variant_id,
                VideoScriptVersion.batch_video_variant_id.in_(owned_variants),
                VideoScriptVersion.idempotency_key == key,
            )
        )

    def list(self, variant_id: int) -> list[VideoScriptVersion]:
        owned_variants = scope_to_owned_products(
            select(BatchVideoVariant.id), BatchVideoVariant, self.session
        )
        return list(
            self.session.scalars(
                select(VideoScriptVersion)
                .options(selectinload(VideoScriptVersion.scenes))
                .where(VideoScriptVersion.batch_video_variant_id == variant_id)
                .where(VideoScriptVersion.batch_video_variant_id.in_(owned_variants))
                .order_by(VideoScriptVersion.version_number.asc())
            ).all()
        )

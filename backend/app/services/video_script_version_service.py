from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import (
    BatchVideoVariant,
    VideoScriptVersion,
    VideoStoryboardSceneVersion,
)
from app.repositories.video_script_version import VideoScriptVersionRepository
from app.schemas.video_script_version import (
    VideoScriptActivateRead,
    VideoScriptCreateRead,
    VideoScriptCreateRequest,
    VideoScriptDraftRequest,
    VideoScriptVersionRead,
)
from app.services.video_script_preflight import VideoScriptPreflightService


class VideoScriptVersionService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = VideoScriptVersionRepository(session)

    def create(
        self, variant_id: int, data: VideoScriptCreateRequest
    ) -> VideoScriptCreateRead:
        draft = VideoScriptDraftRequest.model_validate(
            data.model_dump(
                exclude={
                    "source_digest",
                    "content_digest",
                    "preflight_digest",
                    "preflight_expires_at",
                }
            )
        )
        checked = VideoScriptPreflightService(self.session).run(
            variant_id, draft, expires_at=data.preflight_expires_at
        )
        now = datetime.now(UTC)
        if data.preflight_expires_at.tzinfo is None or data.preflight_expires_at < now:
            raise AppError("Script preflight expired", 409)
        if (
            checked.source_digest,
            checked.content_digest,
            checked.preflight_digest,
        ) != (data.source_digest, data.content_digest, data.preflight_digest):
            raise AppError("Script preflight no longer matches", 409)
        existing = self.repo.get_by_idempotency(variant_id, data.idempotency_key)
        if existing is not None:
            if existing.content_digest != checked.content_digest:
                raise AppError(
                    "Idempotency key is bound to different script content", 409
                )
            return VideoScriptCreateRead(
                version=VideoScriptVersionRead.model_validate(existing), reused=True
            )
        try:
            number = self.session.scalar(
                update(BatchVideoVariant)
                .where(
                    BatchVideoVariant.id == variant_id,
                    BatchVideoVariant.source_digest == checked.variant_source_digest,
                )
                .values(
                    script_version_sequence=BatchVideoVariant.script_version_sequence
                    + 1
                )
                .returning(BatchVideoVariant.script_version_sequence)
            )
            if number is None:
                raise AppError("Frozen Variant identity changed", 409)
            version = VideoScriptVersion(
                batch_video_variant_id=variant_id,
                version_number=number,
                parent_version_id=data.parent_version_id,
                source_type=data.source_type,
                source_digest=checked.source_digest,
                content_digest=checked.content_digest,
                idempotency_key=data.idempotency_key,
                product_id=checked.product_id,
                product_content_digest=checked.product_content_digest,
                strategy_id=checked.strategy_id,
                strategy_digest=checked.strategy_digest,
                copy_matrix_id=checked.copy_matrix_id,
                target_platform_copy_digest=checked.target_platform_copy_digest,
                source_video_project_id=checked.source_video_project_id,
                source_video_project_digest=checked.source_video_project_digest,
                platform=checked.platform,
                language=checked.language,
                creative_angle=checked.creative_angle,
                brand_kit_version_id=checked.brand_kit_version_id,
                brand_kit_version_digest=checked.brand_kit_version_digest,
                title=data.title,
                concept=data.concept,
                hook=data.hook,
                full_narration=checked.full_narration,
                cta=data.cta,
                full_subtitle_draft=checked.full_subtitle_draft,
                created_by_kind="SYSTEM_IMPORT"
                if data.source_type == "VIDEO_PROJECT_IMPORT"
                else "LOCAL_USER",
                review_status="UNREVIEWED",
            )
            self.session.add(version)
            self.session.flush()
            self.session.add_all(
                [
                    VideoStoryboardSceneVersion(
                        video_script_version_id=version.id, **scene.model_dump()
                    )
                    for scene in data.scenes
                ]
            )
            self.session.commit()
            created = self.repo.get(variant_id, version.id)
            assert created is not None
            return VideoScriptCreateRead(
                version=VideoScriptVersionRead.model_validate(created), reused=False
            )
        except IntegrityError as exc:
            self.session.rollback()
            recovered = self.repo.get_by_idempotency(variant_id, data.idempotency_key)
            if recovered is None:
                raise AppError(
                    "Script version conflict; outcome was not retried", 409
                ) from exc
            if recovered.content_digest != checked.content_digest:
                raise AppError(
                    "Idempotency key is bound to different script content", 409
                ) from exc
            return VideoScriptCreateRead(
                version=VideoScriptVersionRead.model_validate(recovered), reused=True
            )

    def list(self, variant_id: int) -> list[VideoScriptVersionRead]:
        variant = self._variant(variant_id)
        return [
            self._read(item, variant.active_script_version_id)
            for item in self.repo.list(variant_id)
        ]

    def get(self, variant_id: int, version_id: int) -> VideoScriptVersionRead:
        item = self.repo.get(variant_id, version_id)
        if item is None:
            raise AppError("Script version was not found", 404)
        active_id = self._variant(variant_id).active_script_version_id
        return self._read(item, active_id)

    def activate(self, variant_id: int, version_id: int) -> VideoScriptActivateRead:
        variant = self._variant(variant_id)
        if self.repo.get(variant_id, version_id) is None:
            raise AppError("Script version was not found", 404)
        reused = variant.active_script_version_id == version_id
        if not reused:
            variant.active_script_version_id = version_id
            self.session.commit()
        return VideoScriptActivateRead(
            variant_id=variant_id,
            active_script_version_id=version_id,
            editing_state="ACTIVE_VERSION",
            reused=reused,
        )

    def _variant(self, variant_id: int) -> BatchVideoVariant:
        item = self.session.get(BatchVideoVariant, variant_id)
        if item is None:
            raise AppError("Script version was not found", 404)
        return item

    @staticmethod
    def _read(
        item: VideoScriptVersion, active_id: int | None
    ) -> VideoScriptVersionRead:
        return VideoScriptVersionRead.model_validate(item).model_copy(
            update={"is_active": item.id == active_id}
        )

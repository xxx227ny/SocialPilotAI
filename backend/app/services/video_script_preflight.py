from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import (
    BatchVideoVariant,
    BrandKitVersion,
    CopyMatrix,
    MarketingStrategy,
    Product,
    VideoProject,
)
from app.models.product import utc_now
from app.models.video_script_version import VideoScriptVersion
from app.schemas.video_script_version import (
    VideoScriptDraftRequest,
    VideoScriptPreflightRead,
)

SCRIPT_CONTRACT_VERSION = "video-script-version-v1"


def stable_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
    ).hexdigest()


def _model_payload(instance: object, fields: tuple[str, ...]) -> dict[str, object]:
    return {field: getattr(instance, field) for field in fields}


class VideoScriptPreflightService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def run(
        self,
        variant_id: int,
        data: VideoScriptDraftRequest,
        *,
        expires_at: datetime | None = None,
    ) -> VideoScriptPreflightRead:
        variant = self.session.get(BatchVideoVariant, variant_id)
        if variant is None:
            raise AppError("Script version was not found", 404)
        if variant.status != "READY_FOR_SCRIPT":
            raise AppError("Variant is not ready for script versioning", 409)
        self._validate_timeline(variant, data)
        parent = None
        if data.parent_version_id is not None:
            parent = self.session.scalar(
                select(VideoScriptVersion).where(
                    VideoScriptVersion.id == data.parent_version_id,
                    VideoScriptVersion.batch_video_variant_id == variant.id,
                )
            )
            if parent is None:
                raise AppError("Script version was not found", 404)
        product = self.session.get(Product, variant.product_id)
        if product is None:
            raise AppError("Script source is unavailable", 409)
        product_digest = stable_digest(
            _model_payload(
                product,
                (
                    "id",
                    "name",
                    "category",
                    "description",
                    "selling_points",
                    "target_markets",
                ),
            )
        )
        brand = (
            self.session.get(BrandKitVersion, variant.brand_kit_version_id)
            if variant.brand_kit_version_id
            else None
        )
        if variant.brand_kit_version_id is not None and (
            brand is None or brand.digest != variant.brand_kit_version_digest
        ):
            raise AppError("Frozen BrandKitVersion identity changed", 409)
        strategy, strategy_digest = self._strategy(data.strategy_id, product.id)
        copy, copy_digest = self._copy(
            data.copy_matrix_id, product.id, strategy, variant.platform
        )
        project, project_digest = self._project(data, product.id, variant)
        content_text = " ".join(
            [data.title, data.concept, data.hook, data.cta]
            + [
                value
                for scene in data.scenes
                for value in (
                    scene.visual_description,
                    scene.action_description,
                    scene.narration,
                    scene.subtitle_draft,
                )
            ]
        ).casefold()
        if brand is not None:
            for forbidden in brand.forbidden_terms:
                term = " ".join(str(forbidden).split()).casefold()
                if term and term in content_text:
                    raise AppError("Script contains a BrandKit forbidden term", 422)
        scenes = [scene.model_dump(mode="json") for scene in data.scenes]
        full_narration = " ".join(scene.narration for scene in data.scenes)
        full_subtitle = " ".join(scene.subtitle_draft for scene in data.scenes)
        source_payload = {
            "contract": SCRIPT_CONTRACT_VERSION,
            "variant_id": variant.id,
            "variant_source_digest": variant.source_digest,
            "product_id": product.id,
            "product_content_digest": product_digest,
            "strategy_id": strategy.id if strategy else None,
            "strategy_digest": strategy_digest,
            "copy_matrix_id": copy.id if copy else None,
            "target_platform_copy_digest": copy_digest,
            "source_video_project_id": project.id if project else None,
            "source_video_project_digest": project_digest,
            "brand_kit_version_id": variant.brand_kit_version_id,
            "brand_kit_version_digest": variant.brand_kit_version_digest,
            "parent_version_id": parent.id if parent else None,
            "parent_content_digest": parent.content_digest if parent else None,
        }
        content_payload = {
            "source_type": data.source_type,
            "platform": variant.platform,
            "language": variant.language,
            "creative_angle": variant.creative_angle,
            "title": data.title,
            "concept": data.concept,
            "hook": data.hook,
            "cta": data.cta,
            "scenes": scenes,
            "full_narration": full_narration,
            "full_subtitle_draft": full_subtitle,
        }
        source_digest = stable_digest(source_payload)
        content_digest = stable_digest(content_payload)
        expiry = expires_at or utc_now() + timedelta(minutes=10)
        preflight_digest = stable_digest(
            {
                "source_digest": source_digest,
                "content_digest": content_digest,
                "expires_at": expiry.isoformat(),
            }
        )
        return VideoScriptPreflightRead(
            ready=True,
            variant_id=variant.id,
            variant_source_digest=variant.source_digest,
            product_id=product.id,
            product_content_digest=product_digest,
            strategy_id=strategy.id if strategy else None,
            strategy_digest=strategy_digest,
            copy_matrix_id=copy.id if copy else None,
            target_platform_copy_digest=copy_digest,
            source_video_project_id=project.id if project else None,
            source_video_project_digest=project_digest,
            brand_kit_version_id=variant.brand_kit_version_id,
            brand_kit_version_digest=variant.brand_kit_version_digest,
            platform=variant.platform,
            language=variant.language,
            creative_angle=variant.creative_angle,
            source_digest=source_digest,
            content_digest=content_digest,
            preflight_digest=preflight_digest,
            expires_at=expiry,
            full_narration=full_narration,
            full_subtitle_draft=full_subtitle,
            current_stage_cost=Decimal("0"),
            cost_scope="manual_versioning_only",
            provider_call_count=0,
            review_status="UNREVIEWED",
            database_writes=0,
        )

    @staticmethod
    def _validate_timeline(
        variant: BatchVideoVariant, data: VideoScriptDraftRequest
    ) -> None:
        expected = 0
        for index, scene in enumerate(data.scenes, 1):
            if (
                scene.sequence != index
                or scene.start_ms != expected
                or scene.end_ms <= scene.start_ms
            ):
                raise AppError(
                    "Storyboard timeline must be continuous and ordered", 422
                )
            expected = scene.end_ms
        if expected != variant.duration_seconds * 1000:
            raise AppError("Storyboard duration must equal the Variant duration", 422)

    def _strategy(
        self, strategy_id: int | None, product_id: int
    ) -> tuple[MarketingStrategy | None, str | None]:
        if strategy_id is None:
            return None, None
        item = self.session.get(MarketingStrategy, strategy_id)
        if item is None or item.product_id != product_id:
            raise AppError("Script source is unavailable", 404)
        return item, stable_digest(
            _model_payload(
                item,
                (
                    "id",
                    "product_id",
                    "positioning",
                    "audience_insights",
                    "angles",
                    "risks",
                    "evidence",
                ),
            )
        )

    def _copy(
        self,
        copy_id: int | None,
        product_id: int,
        strategy: MarketingStrategy | None,
        platform: str,
    ) -> tuple[CopyMatrix | None, str | None]:
        if copy_id is None:
            return None, None
        item = self.session.get(CopyMatrix, copy_id)
        if (
            item is None
            or item.product_id != product_id
            or (strategy is not None and item.marketing_strategy_id != strategy.id)
        ):
            raise AppError("Script source is unavailable", 404)
        selected = next(
            (
                copy
                for copy in item.copies
                if str(copy.get("platform", "")).casefold() == platform.casefold()
            ),
            None,
        )
        if selected is None:
            raise AppError("Target-platform copy is unavailable", 409)
        return item, stable_digest(selected)

    def _project(
        self, data: VideoScriptDraftRequest, product_id: int, variant: BatchVideoVariant
    ) -> tuple[VideoProject | None, str | None]:
        if data.source_video_project_id is None:
            return None, None
        item = self.session.get(VideoProject, data.source_video_project_id)
        if item is None or item.product_id != product_id:
            raise AppError("Script source is unavailable", 404)
        if (
            item.platform.casefold() != variant.platform.casefold()
            or item.duration_seconds != variant.duration_seconds
            or item.aspect_ratio != variant.aspect_ratio
        ):
            raise AppError(
                "VideoProject does not match the exact Variant contract", 409
            )
        payload = _model_payload(
            item,
            (
                "id",
                "product_id",
                "marketing_strategy_id",
                "copy_matrix_id",
                "platform",
                "title",
                "concept",
                "duration_seconds",
                "aspect_ratio",
                "scenes",
                "cta",
                "status",
            ),
        )
        return item, stable_digest(payload)

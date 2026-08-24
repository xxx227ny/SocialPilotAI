from __future__ import annotations

import hashlib
import json

from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import BatchVideoVariant, ProductAsset, VideoProject, VideoScriptVersion
from app.schemas.product_marketing_video import (
    ProductImageShotRequest,
    ProductVideoPrepareRead,
    ProductVideoPrepareRequest,
)
from app.services.video_script_source_identity import (
    validate_video_script_source_identity,
)

PLATFORMS = {
    "TIKTOK": "TikTok",
    "YOUTUBE_SHORTS": "YouTube Shorts",
    "INSTAGRAM_REELS": "Instagram Reels",
}


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


class VideoScriptProjectBridge:
    def __init__(self, session: Session) -> None:
        self.session = session

    def prepare(
        self, product_id: int, data: ProductVideoPrepareRequest
    ) -> ProductVideoPrepareRead:
        variant = self.session.get(BatchVideoVariant, data.variant_id)
        version = self.session.get(VideoScriptVersion, data.script_version_id)
        if (
            variant is None
            or version is None
            or variant.product_id != product_id
            or version.product_id != product_id
            or version.batch_video_variant_id != variant.id
        ):
            raise AppError("Video source not found", 404)
        if (
            variant.status != "READY_FOR_SCRIPT"
            or variant.active_script_version_id != version.id
        ):
            raise AppError("Exact active ScriptVersion is required", 409)
        if version.content_digest != version.content_digest.lower():
            raise AppError("ScriptVersion digest is invalid", 409)
        expected_platform = {
            "tiktok": "TIKTOK",
            "youtube": "YOUTUBE_SHORTS",
            "instagram": "INSTAGRAM_REELS",
        }[variant.platform]
        if data.platform != expected_platform:
            raise AppError("Platform does not match Variant", 409)
        source_identity = validate_video_script_source_identity(
            self.session,
            version,
            product_id=product_id,
            platform=variant.platform,
        )
        scenes = list(version.scenes)
        if len(data.shots) != len(scenes):
            raise AppError("Every ScriptVersion Scene requires an image", 422)
        frozen: list[ProductImageShotRequest] = []
        for scene, requested in zip(scenes, data.shots, strict=True):
            asset = self.session.get(ProductAsset, requested.product_asset_id)
            if (
                scene.id != requested.scene_id
                or asset is None
                or asset.product_id != product_id
                or asset.sha256 != requested.product_asset_sha256
                or not asset.storage_identity
            ):
                raise AppError("Product image identity is invalid", 409)
            frozen.append(requested)
        material = {
            "variant_id": variant.id,
            "variant_source_digest": variant.source_digest,
            "script_version_id": version.id,
            "script_content_digest": version.content_digest,
            "brand_kit_version_id": version.brand_kit_version_id,
            "brand_kit_version_digest": version.brand_kit_version_digest,
            "platform": data.platform,
            "shots": [item.model_dump() for item in frozen],
        }
        input_digest = _digest(material)
        existing = (
            self.session.query(VideoProject)
            .filter_by(source_script_version_id=version.id)
            .one_or_none()
        )
        if existing is not None:
            if existing.source_script_content_digest != version.content_digest:
                raise AppError("ScriptVersion bridge digest conflict", 409)
            return ProductVideoPrepareRead(
                video_project_id=existing.id,
                script_version_id=version.id,
                reused=True,
                input_digest=input_digest,
                shots=frozen,
            )
        project = VideoProject(
            product_id=product_id,
            marketing_strategy_id=source_identity.strategy.id,
            copy_matrix_id=(
                source_identity.copy_matrix.id if source_identity.copy_matrix else None
            ),
            platform=PLATFORMS[data.platform],
            title=version.title,
            concept=version.concept,
            duration_seconds=15,
            aspect_ratio="9:16",
            scenes=[
                {
                    "sequence": scene.sequence,
                    "duration_seconds": (scene.end_ms - scene.start_ms) // 1000,
                    "shot_type": scene.shot_type,
                    "visual_description": scene.visual_description,
                    "action": scene.action_description,
                    "narration": scene.narration,
                    "subtitle_draft": scene.subtitle_draft,
                    "source_product_asset_id": shot.product_asset_id,
                    "source_product_asset_sha256": shot.product_asset_sha256,
                    "motion": shot.motion,
                }
                for scene, shot in zip(scenes, frozen, strict=True)
            ],
            cta=version.cta,
            status="planned",
            source_script_version_id=version.id,
            source_script_content_digest=version.content_digest,
        )
        if any((scene.end_ms - scene.start_ms) % 1000 for scene in scenes):
            raise AppError(
                "Scene boundaries must use whole seconds for local rendering", 422
            )
        self.session.add(project)
        self.session.commit()
        self.session.refresh(project)
        return ProductVideoPrepareRead(
            video_project_id=project.id,
            script_version_id=version.id,
            reused=False,
            input_digest=input_digest,
            shots=frozen,
        )

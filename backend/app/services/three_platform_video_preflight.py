from __future__ import annotations

import hashlib
import json
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.models import BatchVideoVariant, ProductAsset, VideoScriptVersion
from app.providers.happyhorse_provider import (
    HAPPYHORSE_MODEL,
    TOKEN_PLAN_VIDEO_ENDPOINT,
)
from app.providers.live_configuration import (
    effective_qwen_api_key,
    effective_wanx_api_key,
)
from app.schemas.product_marketing_video import (
    PlatformVideoProductionEstimate,
    ThreePlatformVideoPreflightRead,
    ThreePlatformVideoPreflightRequest,
)
from app.services.video_script_source_identity import (
    validate_video_script_source_identity,
)

PLATFORM_ORDER = ("tiktok", "youtube", "instagram")


class ThreePlatformVideoPreflightService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def run(
        self, product_id: int, data: ThreePlatformVideoPreflightRequest
    ) -> ThreePlatformVideoPreflightRead:
        reference = self.session.get(ProductAsset, data.reference_product_asset_id)
        if (
            reference is None
            or reference.product_id != product_id
            or reference.sha256 != data.reference_product_asset_sha256
            or not reference.storage_identity
            or reference.content_type not in {"image/png", "image/jpeg", "image/webp"}
        ):
            raise AppError("Three-platform reference image was not found", 404)
        if (
            len({item.variant_id for item in data.selections}) != 3
            or len({item.script_version_id for item in data.selections}) != 3
        ):
            raise AppError("Three-platform selections must be unique", 422)

        selected: dict[str, tuple[BatchVideoVariant, VideoScriptVersion]] = {}
        for item in data.selections:
            variant = self.session.get(BatchVideoVariant, item.variant_id)
            version = self.session.get(VideoScriptVersion, item.script_version_id)
            if (
                variant is None
                or version is None
                or variant.product_id != product_id
                or variant.status != "READY_FOR_SCRIPT"
                or variant.active_script_version_id != version.id
                or version.batch_video_variant_id != variant.id
                or version.product_id != product_id
                or version.source_type != "QWEN_GENERATED"
                or version.created_by_kind != "QWEN_PROVIDER"
                or version.provider_name != "qwen"
                or version.platform != variant.platform
                or not version.scenes
            ):
                raise AppError("Three-platform source identity is invalid", 409)
            if variant.platform in selected:
                raise AppError(
                    "Three-platform selections must cover each platform", 422
                )
            validate_video_script_source_identity(
                self.session,
                version,
                product_id=product_id,
                platform=variant.platform,
            )
            selected[variant.platform] = (variant, version)
        if set(selected) != set(PLATFORM_ORDER):
            raise AppError("Three-platform selections must cover each platform", 422)

        platforms: list[PlatformVideoProductionEstimate] = []
        for platform in PLATFORM_ORDER:
            variant, version = selected[platform]
            scene_count = len(version.scenes)
            known_cost = (
                self.settings.wanx_image_estimated_cost * scene_count
                + self.settings.happyhorse_estimated_cost
            )
            platforms.append(
                PlatformVideoProductionEstimate(
                    platform=platform,
                    variant_id=variant.id,
                    script_version_id=version.id,
                    scene_count=scene_count,
                    wanx_image_generation_calls=scene_count,
                    known_estimated_cost=known_cost,
                )
            )

        missing = self._missing_requirements()
        material = {
            "contract": "three-platform-product-video-preflight-v1",
            "product_id": product_id,
            "reference_product_asset_id": reference.id,
            "reference_product_asset_sha256": reference.sha256,
            "platforms": [item.model_dump(mode="json") for item in platforms],
            "wanx_image_model": self.settings.wanx_image_model,
            "happyhorse_model": self.settings.happyhorse_model,
            "qwen_tts_model": self.settings.qwen_tts_model,
            "unpriced_cost_components": ["qwen_tts"],
        }
        digest = hashlib.sha256(
            json.dumps(material, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        wanx_calls = sum(item.wanx_image_generation_calls for item in platforms)
        return ThreePlatformVideoPreflightRead(
            **data.model_dump(),
            input_digest=digest,
            platforms=platforms,
            wanx_image_generation_calls=wanx_calls,
            happyhorse_generation_calls=3,
            qwen_tts_generation_calls=3,
            known_estimated_cost=sum(
                (item.known_estimated_cost for item in platforms), Decimal("0")
            ),
            ready=not missing,
            missing_requirements=missing,
            provider_call_count=wanx_calls + 6,
        )

    def _missing_requirements(self) -> list[str]:
        missing: list[str] = []
        flags = {
            "real_product_video_disabled": self.settings.enable_real_product_video,
            "happyhorse_execution_disabled": (
                self.settings.enable_happyhorse_product_video
            ),
            "video_render_execution_disabled": (
                self.settings.enable_video_render_execution
            ),
            "video_composition_disabled": self.settings.enable_video_composition,
            "video_enhancement_disabled": (
                self.settings.enable_video_composition_enhancement
            ),
        }
        missing.extend(name for name, enabled in flags.items() if not enabled)
        if not effective_qwen_api_key(self.settings):
            missing.append("qwen_credentials")
        if not effective_wanx_api_key(self.settings):
            missing.append("wanx_credentials")
        if self.settings.happyhorse_endpoint.rstrip("/") != TOKEN_PLAN_VIDEO_ENDPOINT:
            missing.append("happyhorse_endpoint")
        if self.settings.happyhorse_model != HAPPYHORSE_MODEL:
            missing.append("happyhorse_model")
        if not (self.settings.product_asset_storage_root or "").strip():
            missing.append("product_asset_storage")
        if not (self.settings.video_artifact_storage_root or "").strip():
            missing.append("video_artifact_storage")
        return missing

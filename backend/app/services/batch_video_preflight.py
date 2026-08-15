from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import AppError
from app.models import Product
from app.models.product import utc_now
from app.schemas.batch_video import (
    BatchVideoPreflightRead,
    BatchVideoRequest,
    BatchVideoVariantPlan,
)

BATCH_VIDEO_CONTRACT_VERSION = "batch-video-orchestration-v1"
MAX_BATCH_VARIANTS = 60


def stable_digest(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def variant_source_payload(
    *,
    product_id: int,
    platform: str,
    variant_index: int,
    duration_seconds: int,
    aspect_ratio: str,
    language: str,
    creative_angle: str | None,
    brand_kit_version_id: int | None,
    brand_kit_version_digest: str | None,
) -> dict[str, object]:
    return {
        "contract_version": BATCH_VIDEO_CONTRACT_VERSION,
        "product_id": product_id,
        "platform": platform,
        "variant_index": variant_index,
        "duration_seconds": duration_seconds,
        "aspect_ratio": aspect_ratio,
        "language": language,
        "creative_angle": creative_angle,
        "brand_kit_version_id": brand_kit_version_id,
        "brand_kit_version_digest": brand_kit_version_digest,
    }


class BatchVideoPreflightService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def run(
        self, data: BatchVideoRequest, *, expires_at: datetime | None = None
    ) -> BatchVideoPreflightRead:
        if len(set(data.product_ids)) != len(data.product_ids):
            raise AppError("Product IDs must be distinct", 422)
        if len(set(data.platforms)) != len(data.platforms):
            raise AppError("Platforms must be distinct", 422)
        product_ids = sorted(data.product_ids)
        platforms = sorted(data.platforms)
        total = len(product_ids) * len(platforms) * data.variants_per_platform
        if total > MAX_BATCH_VARIANTS:
            raise AppError("Batch variant limit exceeded", 422)
        if data.max_concurrency > total:
            raise AppError("Maximum concurrency exceeds variant count", 422)
        products = list(
            self.session.scalars(
                select(Product)
                .options(selectinload(Product.brand_kit_version))
                .where(Product.id.in_(product_ids))
                .order_by(Product.id)
            ).all()
        )
        if [product.id for product in products] != product_ids:
            raise AppError("One or more products were not found", 404)
        plans: list[BatchVideoVariantPlan] = []
        for product in products:
            brand = product.brand_kit_version
            if product.brand_kit_version_id is not None and brand is None:
                raise AppError("Product BrandKitVersion is unavailable", 409)
            for platform in platforms:
                for index in range(1, data.variants_per_platform + 1):
                    payload = variant_source_payload(
                        product_id=product.id,
                        platform=platform,
                        variant_index=index,
                        duration_seconds=data.duration_seconds,
                        aspect_ratio=data.aspect_ratio,
                        language=data.language,
                        creative_angle=data.creative_angle,
                        brand_kit_version_id=brand.id if brand else None,
                        brand_kit_version_digest=brand.digest if brand else None,
                    )
                    plans.append(
                        BatchVideoVariantPlan(
                            product_id=product.id,
                            platform=platform,
                            variant_index=index,
                            brand_kit_version_id=brand.id if brand else None,
                            brand_kit_version_digest=brand.digest if brand else None,
                            source_digest=stable_digest(payload),
                        )
                    )
        frozen = {
            "contract_version": BATCH_VIDEO_CONTRACT_VERSION,
            "product_ids": product_ids,
            "platforms": platforms,
            "variants_per_platform": data.variants_per_platform,
            "duration_seconds": data.duration_seconds,
            "aspect_ratio": data.aspect_ratio,
            "language": data.language,
            "priority": data.priority,
            "max_concurrency": data.max_concurrency,
            "creative_angle": data.creative_angle,
            "variants": [plan.model_dump(mode="json") for plan in plans],
        }
        request_digest = stable_digest(frozen)
        expires_at = expires_at or (utc_now() + timedelta(minutes=10))
        preflight_digest = stable_digest(
            {"request_digest": request_digest, "expires_at": expires_at.isoformat()}
        )
        return BatchVideoPreflightRead(
            ready=True,
            contract_version=BATCH_VIDEO_CONTRACT_VERSION,
            request_digest=request_digest,
            preflight_digest=preflight_digest,
            expires_at=expires_at,
            variant_count=total,
            max_concurrency=data.max_concurrency,
            variants=plans,
            current_stage_cost=Decimal("0"),
            currency="USD",
            cost_scope="orchestration_only",
            downstream_provider_cost_status="NOT_ESTIMATED",
            provider_call_count=0,
            ffmpeg_call_count=0,
        )

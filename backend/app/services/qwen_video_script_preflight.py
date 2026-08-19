from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.models import (
    BatchVideoJob,
    BatchVideoVariant,
    BrandKitVersion,
    CopyMatrix,
    MarketingStrategy,
    Product,
)
from app.models.product import utc_now
from app.models.video_script_version import VideoScriptVersion
from app.schemas.video_script_version import (
    QwenScriptPreflightRead,
    QwenScriptPreflightRequest,
)
from app.services.video_script_preflight import _model_payload, stable_digest

PROMPT_CONTRACT_VERSION = "qwen-video-script-prompt-v1"
OUTPUT_SCHEMA_VERSION = "qwen-video-script-output-v1"


class QwenVideoScriptPreflightService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def run(
        self,
        variant_id: int,
        data: QwenScriptPreflightRequest,
        *,
        expires_at: datetime | None = None,
    ) -> QwenScriptPreflightRead:
        if not self.settings.enable_qwen_video_script_generation:
            raise AppError("Qwen script generation is unavailable", 404)
        variant = self.session.get(BatchVideoVariant, variant_id)
        if variant is None:
            raise AppError("Qwen script generation was not found", 404)
        if variant.status != "READY_FOR_SCRIPT":
            raise AppError("Variant is not ready for Qwen script generation", 409)
        if variant.duration_seconds != 15 or variant.aspect_ratio != "9:16":
            raise AppError("Variant does not match the Qwen script contract", 409)
        batch = self.session.get(BatchVideoJob, variant.batch_video_job_id)
        product = self.session.get(Product, variant.product_id)
        if batch is None or product is None:
            raise AppError("Qwen script source is unavailable", 409)

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
            if variant.brand_kit_version_id is not None
            else None
        )
        if variant.brand_kit_version_id is not None and (
            brand is None or brand.digest != variant.brand_kit_version_digest
        ):
            raise AppError("Frozen BrandKitVersion identity changed", 409)

        strategy = self.session.get(MarketingStrategy, data.strategy_id)
        if strategy is None or strategy.product_id != product.id:
            raise AppError("Qwen script source was not found", 404)
        strategy_digest = stable_digest(
            _model_payload(
                strategy,
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
        copy = None
        copy_digest = None
        if data.copy_matrix_id is not None:
            copy = self.session.get(CopyMatrix, data.copy_matrix_id)
            if (
                copy is None
                or copy.product_id != product.id
                or copy.marketing_strategy_id != strategy.id
            ):
                raise AppError("Qwen script source was not found", 404)
            selected = next(
                (
                    item
                    for item in copy.copies
                    if str(item.get("platform", "")).casefold()
                    == variant.platform.casefold()
                ),
                None,
            )
            if selected is None:
                raise AppError("Target-platform copy is unavailable", 409)
            copy_digest = stable_digest(selected)

        parent = None
        if data.parent_version_id is not None:
            parent = self.session.scalar(
                select(VideoScriptVersion).where(
                    VideoScriptVersion.id == data.parent_version_id,
                    VideoScriptVersion.batch_video_variant_id == variant.id,
                )
            )
            if parent is None:
                raise AppError("Qwen script generation was not found", 404)

        frozen = {
            "prompt_contract_version": PROMPT_CONTRACT_VERSION,
            "output_schema_version": OUTPUT_SCHEMA_VERSION,
            "variant_id": variant.id,
            "variant_source_digest": variant.source_digest,
            "product_id": product.id,
            "product_content_digest": product_digest,
            "strategy_id": strategy.id,
            "strategy_digest": strategy_digest,
            "copy_matrix_id": copy.id if copy else None,
            "target_platform_copy_digest": copy_digest,
            "parent_version_id": parent.id if parent else None,
            "parent_content_digest": parent.content_digest if parent else None,
            "brand_kit_version_id": variant.brand_kit_version_id,
            "brand_kit_version_digest": variant.brand_kit_version_digest,
            "platform": variant.platform,
            "language": variant.language,
            "creative_angle": variant.creative_angle,
            "duration_ms": 15000,
            "aspect_ratio": "9:16",
            "provider_name": "qwen",
            "provider_model": self.settings.qwen_model,
            "idempotency_key": data.idempotency_key,
            "estimated_cost_min": (
                str(self.settings.qwen_video_script_cost_min)
                if self.settings.qwen_video_script_cost_min is not None
                else None
            ),
            "estimated_cost_max": (
                str(self.settings.qwen_video_script_cost_max)
                if self.settings.qwen_video_script_cost_max is not None
                else None
            ),
            "currency": self.settings.qwen_video_script_cost_currency,
            "cost_estimate_basis": self.settings.qwen_video_script_cost_basis,
        }
        frozen_digest = stable_digest(frozen)
        expiry = expires_at or utc_now() + timedelta(
            seconds=self.settings.qwen_video_script_preflight_ttl_seconds
        )
        preflight_digest = stable_digest(
            {"frozen_input_digest": frozen_digest, "expires_at": expiry.isoformat()}
        )
        remaining = max(
            batch.qwen_script_call_quota - batch.qwen_script_calls_reserved, 0
        )
        cost_ready = all(
            value is not None
            for value in (
                self.settings.qwen_video_script_cost_min,
                self.settings.qwen_video_script_cost_max,
                self.settings.qwen_video_script_cost_basis,
            )
        )
        return QwenScriptPreflightRead(
            ready_for_execution=cost_ready and remaining > 0,
            variant_id=variant.id,
            variant_source_digest=variant.source_digest,
            product_id=product.id,
            product_content_digest=product_digest,
            strategy_id=strategy.id,
            strategy_digest=strategy_digest,
            copy_matrix_id=copy.id if copy else None,
            target_platform_copy_digest=copy_digest,
            parent_version_id=parent.id if parent else None,
            parent_content_digest=parent.content_digest if parent else None,
            brand_kit_version_id=variant.brand_kit_version_id,
            brand_kit_version_digest=variant.brand_kit_version_digest,
            platform=variant.platform,
            language=variant.language,
            creative_angle=variant.creative_angle,
            duration_ms=15000,
            aspect_ratio="9:16",
            prompt_contract_version=PROMPT_CONTRACT_VERSION,
            output_schema_version=OUTPUT_SCHEMA_VERSION,
            provider_name="qwen",
            provider_model=self.settings.qwen_model,
            frozen_input_digest=frozen_digest,
            preflight_digest=preflight_digest,
            expires_at=expiry,
            estimated_provider_calls=1,
            estimated_cost_min=self.settings.qwen_video_script_cost_min,
            estimated_cost_max=self.settings.qwen_video_script_cost_max,
            currency=self.settings.qwen_video_script_cost_currency,
            cost_estimate_basis=self.settings.qwen_video_script_cost_basis,
            cost_scope="single_qwen_video_script_generation",
            requires_cost_confirmation=True,
            will_auto_activate=False,
            provider_call_count=0,
            database_writes=0,
            quota_limit=batch.qwen_script_call_quota,
            quota_reserved=batch.qwen_script_calls_reserved,
            quota_remaining=remaining,
        )

    def prompt_snapshot(self, checked: QwenScriptPreflightRead) -> dict[str, object]:
        variant = self.session.get(BatchVideoVariant, checked.variant_id)
        product = self.session.get(Product, checked.product_id)
        strategy = self.session.get(MarketingStrategy, checked.strategy_id)
        if variant is None or product is None or strategy is None:
            raise AppError("Frozen Qwen script source changed", 409)
        copy_payload = None
        if checked.copy_matrix_id is not None:
            copy = self.session.get(CopyMatrix, checked.copy_matrix_id)
            if copy is None:
                raise AppError("Frozen Qwen script source changed", 409)
            copy_payload = next(
                item
                for item in copy.copies
                if str(item.get("platform", "")).casefold()
                == checked.platform.casefold()
            )
        brand_payload = None
        if checked.brand_kit_version_id is not None:
            brand = self.session.get(BrandKitVersion, checked.brand_kit_version_id)
            if brand is None:
                raise AppError("Frozen Qwen script source changed", 409)
            brand_payload = {
                "id": brand.id,
                "digest": brand.digest,
                "brand_name": brand.brand_name,
                "positioning": brand.positioning,
                "brand_tone": brand.brand_tone,
                "preferred_terms": brand.preferred_terms,
                "forbidden_terms": brand.forbidden_terms,
                "required_disclosures": brand.required_disclosures,
                "claims_constraints": brand.claims_constraints,
            }
        return {
            "contract": checked.prompt_contract_version,
            "output_schema": checked.output_schema_version,
            "variant": {
                "id": variant.id,
                "platform": checked.platform,
                "language": checked.language,
                "creative_angle": checked.creative_angle,
                "duration_ms": checked.duration_ms,
                "aspect_ratio": checked.aspect_ratio,
            },
            "product": _model_payload(
                product,
                (
                    "id",
                    "name",
                    "category",
                    "description",
                    "selling_points",
                    "target_markets",
                ),
            ),
            "strategy": _model_payload(
                strategy,
                (
                    "id",
                    "positioning",
                    "audience_insights",
                    "angles",
                    "risks",
                    "evidence",
                ),
            ),
            "copy": copy_payload,
            "brand": brand_payload,
            "parent_version_id": checked.parent_version_id,
            "parent_content_digest": checked.parent_content_digest,
        }
